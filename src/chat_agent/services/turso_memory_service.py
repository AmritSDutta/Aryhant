"""Turso / libSQL Personal AI Memory & User Preferences Engine for Aryhant."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

from chat_agent.config import settings

logger = logging.getLogger(__name__)

SKILL_PROMOTION_THRESHOLD = 3
MAX_MEMORY_CONTEXT_ITEMS = 6
KEYWORD_OVERLAP_THRESHOLD = 2

ARYHANT_NAMESPACE = uuid.UUID("7b6a673d-9d41-4b10-8b0f-e28a502a1b94")

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "what", "which",
    "please", "give", "help", "solve", "about", "your", "mine", "tell", "make",
    "each", "when", "where", "how", "why", "who", "will", "would", "could", "should",
    "explain", "practice", "questions", "notes", "grade", "class", "question",
}

MULTI_SCRIPT_TOKEN_RE = re.compile(r"[\w\u0900-\u097F\u0980-\u09FF]+", re.UNICODE)
INJECTION_PATTERN = re.compile(
    r"(?i)(ignore\s+(all\s+)?previous|disregard\s+(all\s+)?previous|new\s+instructions|system\s+prompt|system\s*:|you\s+are\s+now|override|jailbreak|<script|<\s*assistant|forget\s+all)"
)


def sanitize_memory_statement(text: str) -> str | None:
    """Sanitize and validate a candidate memory statement against prompt injection.

    Note: This is a defense-in-depth heuristic filter intended to be paired with untrusted
    <student_learning_context> boundary framing in the system prompt.
    """
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) < 3:
        return None
    # Reject statements longer than 150 characters to prevent buffer stuffing or tail-redaction bypasses
    if len(cleaned) > 150:
        logger.warning("Rejected memory statement exceeding 150-char cap (%d chars): %r", len(cleaned), cleaned[:50])
        return None
    if INJECTION_PATTERN.search(cleaned):
        logger.warning("Rejected memory statement matching injection pattern: %r", cleaned)
        return None
    cleaned = re.sub(r"[<>]", "", cleaned).strip()
    return cleaned if cleaned else None


def tokenize_keywords(text: str) -> list[str]:
    """Extract clean, multi-script tokens (English, Devanagari, Bengali) without punctuation."""
    tokens = MULTI_SCRIPT_TOKEN_RE.findall(text.lower())
    valid = [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]
    return sorted(list(set(valid)))


class TursoMemoryService:
    """Manages persistent student memories, preferences, and skill promotion in Turso/libSQL."""

    def __init__(
        self,
        db_path: str | None = None,
        database_url: str | None = None,
        auth_token: str | None = None,
        sync_url: str | None = None,
    ) -> None:
        self.db_path: str = db_path if db_path is not None else str(settings.resolved_turso_db_path)
        raw_url = (
            database_url
            if database_url is not None
            else (
                sync_url
                if sync_url is not None
                else (os.getenv("ARYHANT_TURSO_DATABASE_URL") or settings.ARYHANT_TURSO_DATABASE_URL)
            )
        )
        url = (raw_url or "").strip().strip("'").strip('"')
        if url.startswith("turso://"):
            url = f"libsql://{url[len('turso://'):]}"
        elif url and not (url.startswith("libsql://") or url.startswith("https://") or url.startswith("http://")):
            url = f"libsql://{url}"
        self.database_url: str = url
        self.sync_url: str = self.database_url
        raw_token = (
            auth_token
            if auth_token is not None
            else (os.getenv("ARYHANT_TURSO_AUTH_TOKEN") or settings.ARYHANT_TURSO_AUTH_TOKEN)
        )
        self.auth_token: str = (raw_token or "").strip().strip("'").strip('"')
        self._write_lock = threading.Lock()
        db_label = f"{self.database_url[:30]}..." if self.database_url else "NONE (local test SQLite)"
        logger.info("TursoMemoryService initialized: database_url=%s, db_path=%s", db_label, self.db_path)

    def _sync_remote(self, conn: Any = None, stage: str = "write") -> None:
        """No-op retained for backwards interface compatibility."""
        pass

    def _get_connection(self, sync_on_read: bool = False) -> Any:
        """Connect directly to remote Turso database using ARYHANT_TURSO_DATABASE_URL, or local SQLite for tests."""
        if self.database_url:
            try:
                import libsql
            except ImportError as err:
                logger.critical("ARYHANT_TURSO_DATABASE_URL is set (%s), but 'libsql' is not installed.", self.database_url)
                raise RuntimeError(
                    "ARYHANT_TURSO_DATABASE_URL is set but 'libsql' package is not installed. "
                    "Install it with `pip install libsql`."
                ) from err

            conn = libsql.connect(
                self.database_url,
                auth_token=self.auth_token,
                isolation_level=None,
            )
            try:
                conn.execute("PRAGMA foreign_keys = ON;")
                logger.info("Connected directly to remote Turso database (%s)", self.database_url[:24])
            except Exception as e:
                logger.warning("Failed to enable foreign keys on remote Turso: %s", e)
            return conn

        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            logger.info("Enabled foreign keys on local SQLite connection (test mode).")
        except Exception as e:
            logger.warning("Failed to enable foreign keys on local SQLite connection: %s", e)
        return conn

    def _ensure_user_profile(
        self,
        cursor: Any,
        user_id: str,
        display_name: str | None = None,
        real_name: str | None = None,
    ) -> None:
        """Ensure parent row exists in user_profiles to satisfy foreign key constraint and track identity."""
        now_ms = int(time.time() * 1000)
        d_name = (display_name or "").strip() or "Aryhant Student"
        r_name = (real_name or "").strip() or "Student"
        cursor.execute(
            """
            INSERT INTO user_profiles (user_id, display_name, real_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = CASE WHEN excluded.display_name != 'Aryhant Student' THEN excluded.display_name ELSE user_profiles.display_name END,
                real_name = CASE WHEN excluded.real_name != 'Student' THEN excluded.real_name ELSE user_profiles.real_name END,
                updated_at = excluded.updated_at;
            """,
            (user_id, d_name, r_name, now_ms, now_ms),
        )

    def update_user_profile(
        self,
        user_id: str,
        display_name: str,
        real_name: str,
    ) -> None:
        """Explicitly update user profile display name and real name with pre and post sync."""
        with self._write_lock:
            conn = self._get_connection(sync_on_read=False)
            try:
                self._sync_remote(conn, stage="pre-write")
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE;")
                self._ensure_user_profile(cursor, user_id, display_name, real_name)
                conn.commit()
                self._sync_remote(conn, stage="post-write")
                logger.info("User profile successfully updated and synced for %s (%s / %s)", user_id, display_name, real_name)
            except Exception as e:
                logger.warning("Error updating user profile for %s: %s", user_id, e)
                try:
                    conn.rollback()
                except Exception as e_rb:
                    logger.warning("Rollback error during update_user_profile for %s: %s", user_id, e_rb)
            finally:
                conn.close()

    async def aupdate_user_profile(
        self,
        user_id: str,
        display_name: str,
        real_name: str,
    ) -> None:
        """Async non-blocking version of update_user_profile."""
        await asyncio.to_thread(self.update_user_profile, user_id, display_name, real_name)

    def get_user_memory_context(self, user_id: str, limit: int = MAX_MEMORY_CONTEXT_ITEMS) -> str:
        """Fetch top weighted memories for prompt injection formatted as concise markdown bullets."""
        default_context = "No specific stored preferences yet; use standard ICSE Grade 5 balanced explanations."
        try:
            conn = self._get_connection(sync_on_read=False)
        except Exception as e:
            logger.warning("Failed to obtain DB connection for %s memory context: %s", user_id, e)
            return default_context

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT kind, text, weight
                FROM memories
                WHERE user_id = ?
                ORDER BY weight DESC, last_seen_at DESC
                LIMIT ?;
                """,
                (user_id, limit),
            )
            rows = cursor.fetchall()
            if not rows:
                return default_context

            bullets: list[str] = []
            for kind, text, weight in rows:
                label = "Skill" if kind == "skill" or weight >= SKILL_PROMOTION_THRESHOLD else kind.capitalize()
                bullets.append(f"- [{label}] {text}")
            return "\n".join(bullets)
        except Exception as e:
            logger.warning("Error fetching memory context for %s: %s", user_id, e)
            return default_context
        finally:
            try:
                conn.close()
            except Exception as e:
                logger.warning("Error closing DB connection for %s memory context: %s", user_id, e)

    async def aget_user_memory_context(self, user_id: str, limit: int = MAX_MEMORY_CONTEXT_ITEMS) -> str:
        """Async non-blocking version of get_user_memory_context."""
        return await asyncio.to_thread(self.get_user_memory_context, user_id, limit)

    def add_manual_preference(
        self,
        user_id: str,
        text: str,
        category: str = "Preference",
        display_name: str | None = None,
        real_name: str | None = None,
    ) -> str:
        """Add an explicit user-defined preference with pre-write and post-write sync."""
        sanitized = sanitize_memory_statement(text)
        if not sanitized:
            return ""

        memory_id = str(uuid.uuid5(ARYHANT_NAMESPACE, f"pref:{user_id}:{sanitized.lower()}"))
        keywords = tokenize_keywords(sanitized)
        now_ms = int(time.time() * 1000)

        with self._write_lock:
            conn = self._get_connection(sync_on_read=False)
            try:
                self._sync_remote(conn, stage="pre-write")
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE;")
                self._ensure_user_profile(cursor, user_id, display_name, real_name)
                cursor.execute(
                    """
                    INSERT INTO memories (id, user_id, kind, text, keywords, weight, source, category, request_id, created_at, updated_at, last_seen_at)
                    VALUES (?, ?, 'preference', ?, ?, 1, 'manual', ?, NULL, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        text = excluded.text,
                        keywords = excluded.keywords,
                        updated_at = excluded.updated_at,
                        last_seen_at = excluded.last_seen_at;
                    """,
                    (memory_id, user_id, sanitized, json.dumps(keywords), category, now_ms, now_ms, now_ms),
                )
                conn.commit()
                self._sync_remote(conn, stage="post-write")
                logger.info("Added manual preference for %s: %s", user_id, sanitized)
                return memory_id
            except Exception as e:
                logger.warning("Failed to add manual preference for %s: %s", user_id, e)
                try:
                    conn.rollback()
                except Exception as e_rb:
                    logger.warning("Rollback error during add_manual_preference for %s: %s", user_id, e_rb)
                return ""
            finally:
                conn.close()

    async def aadd_manual_preference(
        self,
        user_id: str,
        text: str,
        category: str = "Preference",
        display_name: str | None = None,
        real_name: str | None = None,
    ) -> str:
        """Async non-blocking version of add_manual_preference."""
        return await asyncio.to_thread(self.add_manual_preference, user_id, text, category, display_name, real_name)

    def remember_pattern(
        self,
        user_id: str,
        text: str,
        category: str = "General",
        request_id: str | None = None,
        display_name: str | None = None,
        real_name: str | None = None,
    ) -> None:
        """Record or reinforce a learned learning pattern with pre-write and post-write sync."""
        sanitized = sanitize_memory_statement(text)
        if not sanitized:
            return

        new_keywords = set(tokenize_keywords(sanitized))
        if not new_keywords:
            return

        now_ms = int(time.time() * 1000)
        with self._write_lock:
            conn = self._get_connection(sync_on_read=False)
            try:
                self._sync_remote(conn, stage="pre-write")
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE;")
                self._ensure_user_profile(cursor, user_id, display_name, real_name)
                cursor.execute(
                    "SELECT id, text, keywords, weight, kind FROM memories WHERE user_id = ?;",
                    (user_id,),
                )
                existing = cursor.fetchall()

                best_match_id: str | None = None
                best_overlap = 0
                best_weight = 1
                best_kind = "pattern"

                for mem_id, _, kw_json, weight, kind in existing:
                    try:
                        kws = set(json.loads(kw_json))
                    except Exception as e:
                        logger.warning("Failed to parse keywords JSON for memory %s: %s", mem_id, e)
                        kws = set()
                    overlap = len(new_keywords.intersection(kws))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_match_id = mem_id
                        best_weight = weight
                        best_kind = kind

                if best_match_id and best_overlap >= KEYWORD_OVERLAP_THRESHOLD:
                    new_weight = best_weight + 1
                    new_kind = "skill" if (new_weight >= SKILL_PROMOTION_THRESHOLD or best_kind == "skill") else best_kind
                    cursor.execute(
                        """
                        UPDATE memories
                        SET weight = ?, kind = ?, last_seen_at = ?, updated_at = ?
                        WHERE id = ?;
                        """,
                        (new_weight, new_kind, now_ms, now_ms, best_match_id),
                    )
                    logger.info(
                        "Reinforced memory %s for %s (weight=%d, kind=%s)",
                        best_match_id, user_id, new_weight, new_kind
                    )
                else:
                    mem_id = str(uuid.uuid5(ARYHANT_NAMESPACE, f"pattern:{user_id}:{sanitized.lower()}"))
                    cursor.execute(
                        """
                        INSERT INTO memories (id, user_id, kind, text, keywords, weight, source, category, request_id, created_at, updated_at, last_seen_at)
                        VALUES (?, ?, 'pattern', ?, ?, 1, 'request', ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            weight = weight + 1,
                            kind = CASE WHEN weight + 1 >= 3 THEN 'skill' ELSE kind END,
                            last_seen_at = excluded.last_seen_at,
                            updated_at = excluded.updated_at;
                        """,
                        (mem_id, user_id, sanitized, json.dumps(sorted(list(new_keywords))), category, request_id, now_ms, now_ms, now_ms),
                    )
                    logger.info("Recorded new learning pattern for %s: %s", user_id, sanitized)

                conn.commit()
                self._sync_remote(conn, stage="post-write")
                logger.info("Pattern memory successfully committed and synced for %s: %s", user_id, sanitized)
            except Exception as e:
                logger.warning("Error in remember_pattern for %s: %s", user_id, e)
                try:
                    conn.rollback()
                except Exception as e_rb:
                    logger.warning("Rollback error during remember_pattern for %s: %s", user_id, e_rb)
            finally:
                conn.close()

    async def aremember_pattern(
        self,
        user_id: str,
        text: str,
        category: str = "General",
        request_id: str | None = None,
        display_name: str | None = None,
        real_name: str | None = None,
    ) -> None:
        """Async non-blocking version of remember_pattern."""
        await asyncio.to_thread(self.remember_pattern, user_id, text, category, request_id, display_name, real_name)

    def list_user_memories(self, user_id: str) -> list[dict[str, Any]]:
        """List all active memories, preferences, and skills for user."""
        conn = self._get_connection(sync_on_read=False)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, kind, text, keywords, weight, source, category, created_at, last_seen_at
                FROM memories
                WHERE user_id = ?
                ORDER BY weight DESC, last_seen_at DESC;
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            results: list[dict[str, Any]] = []
            for r in rows:
                results.append({
                    "id": r[0],
                    "kind": r[1],
                    "text": r[2],
                    "keywords": json.loads(r[3]) if r[3] else [],
                    "weight": r[4],
                    "source": r[5],
                    "category": r[6] or "General",
                    "created_at": r[7],
                    "last_seen_at": r[8],
                    "is_skill": r[1] == "skill" or r[4] >= SKILL_PROMOTION_THRESHOLD,
                })
            return results
        except Exception as e:
            logger.warning("Error listing memories for %s: %s", user_id, e)
            return []
        finally:
            conn.close()

    async def alist_user_memories(self, user_id: str) -> list[dict[str, Any]]:
        """Async non-blocking version of list_user_memories."""
        return await asyncio.to_thread(self.list_user_memories, user_id)

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """Delete a single memory entry belonging to user with pre and post sync."""
        with self._write_lock:
            conn = self._get_connection(sync_on_read=False)
            try:
                self._sync_remote(conn, stage="pre-write")
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE;")
                cursor.execute("DELETE FROM memories WHERE id = ? AND user_id = ?;", (memory_id, user_id))
                conn.commit()
                deleted = cursor.rowcount > 0
                self._sync_remote(conn, stage="post-write")
                logger.info("Deleted memory %s for %s: success=%s", memory_id, user_id, deleted)
                return deleted
            except Exception as e:
                logger.warning("Error deleting memory %s for %s: %s", memory_id, user_id, e)
                try:
                    conn.rollback()
                except Exception as e_rb:
                    logger.warning("Rollback error during delete_memory for %s: %s", user_id, e_rb)
                return False
            finally:
                conn.close()

    async def adelete_memory(self, user_id: str, memory_id: str) -> bool:
        """Async non-blocking version of delete_memory."""
        return await asyncio.to_thread(self.delete_memory, user_id, memory_id)

    def clear_user_memories(self, user_id: str) -> int:
        """Clear all memories for a user with pre and post sync."""
        with self._write_lock:
            conn = self._get_connection(sync_on_read=False)
            try:
                self._sync_remote(conn, stage="pre-write")
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE;")
                cursor.execute("DELETE FROM memories WHERE user_id = ?;", (user_id,))
                conn.commit()
                count = cursor.rowcount
                self._sync_remote(conn, stage="post-write")
                logger.info("Cleared %d memories for user %s", count, user_id)
                return count
            except Exception as e:
                logger.warning("Error clearing memories for %s: %s", user_id, e)
                try:
                    conn.rollback()
                except Exception as e_rb:
                    logger.warning("Rollback error during clear_user_memories for %s: %s", user_id, e_rb)
                return 0
            finally:
                conn.close()

    async def aclear_user_memories(self, user_id: str) -> int:
        """Async non-blocking version of clear_user_memories."""
        return await asyncio.to_thread(self.clear_user_memories, user_id)

    async def extract_and_reinforce(
        self,
        user_id: str,
        user_text: str,
        assistant_reply: str,
        display_name: str | None = None,
        real_name: str | None = None,
    ) -> None:
        """Asynchronous background distillation: extract clean learning habits via fast LLM."""
        if not user_text or len(user_text.strip()) < 10:
            return

        provider = getattr(settings, "MODEL_PROVIDER", "gemini").lower()
        if not provider or provider not in ("nebius", "gemini"):
            provider = getattr(settings, "QUESTION_GENERATOR_PROVIDER", "gemini").lower()

        distill_prompt = (
            "Analyze this Grade 5 student message and AI response. "
            "Extract 1 concise pedagogical learning habit, recurring topic interest, or explanation preference if present. "
            "Never include personal names, ages, phone numbers, or private details. "
            "If nothing noteworthy or general greeting, return null.\n"
            f"Student: {user_text[:400]}\n"
            f"Assistant: {assistant_reply[:400]}\n\n"
            'Output valid JSON only: {"statement": "...", "category": "Mathematics|Science|Language|Tone"} or null'
        )

        try:
            extracted: dict[str, str] | None = None
            if provider == "nebius" and bool(settings.nebius_api_key):
                import openai
                client = openai.AsyncOpenAI(
                    base_url=getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
                    api_key=settings.nebius_api_key,
                )
                nebius_model = getattr(settings, "nebius_question_model", "") or getattr(settings, "NEBIUS_QUESTION_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
                try:
                    resp = await client.chat.completions.create(
                        model=nebius_model,
                        messages=[{"role": "user", "content": distill_prompt}],
                        temperature=0.2,
                        max_tokens=256,
                        response_format={"type": "json_object"},
                    )
                except Exception as e_rf:
                    logger.warning("Nebius json_object response_format failed (%s), retrying standard completion: %s", nebius_model, e_rf)
                    resp = await client.chat.completions.create(
                        model=nebius_model,
                        messages=[{"role": "user", "content": distill_prompt}],
                        temperature=0.2,
                        max_tokens=256,
                    )
                content = resp.choices[0].message.content or ""
                try:
                    extracted = json.loads(content)
                    logger.info("Parsed Nebius JSON distillation response: %s", extracted)
                except Exception as e:
                    logger.warning("Direct JSON decode failed for Nebius response (%s), trying regex: %s", content[:80], e)
                    match = re.search(r"\{.*?\}", content, re.DOTALL)
                    if match:
                        extracted = json.loads(match.group(0))
                        logger.info("Regex fallback successfully decoded Nebius JSON: %s", extracted)
            else:
                from google import genai
                from google.genai import types

                model_name = (
                    getattr(settings, "question_generator_model", "")
                    or getattr(settings, "QUESTION_GENERATOR_MODEL", "")
                    or "gemini-flash-lite-latest"
                )
                client = genai.Client(api_key=settings.api_key)
                resp = await client.aio.models.generate_content(
                    model=model_name,
                    contents=distill_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.2,
                    ),
                )
                text_out = resp.text or ""
                try:
                    extracted = json.loads(text_out)
                    logger.info("Parsed Gemini JSON distillation response: %s", extracted)
                except Exception as e:
                    logger.warning("Direct JSON decode failed for Gemini response (%s), trying regex: %s", text_out[:80], e)
                    match = re.search(r"\{.*?\}", text_out, re.DOTALL)
                    if match:
                        extracted = json.loads(match.group(0))
                        logger.info("Regex fallback successfully decoded Gemini JSON: %s", extracted)

            if extracted and isinstance(extracted, dict) and extracted.get("statement"):
                stmt = str(extracted["statement"]).strip()
                cat = str(extracted.get("category", "General")).strip()
                if stmt and stmt.lower() != "null":
                    await self.aremember_pattern(
                        user_id=user_id,
                        text=stmt,
                        category=cat,
                        display_name=display_name,
                        real_name=real_name,
                    )
                    logger.info("Successfully extracted and recorded memory pattern for %s: %s (category=%s)", user_id, stmt, cat)
        except Exception as e:
            logger.warning("Background memory extraction notice for %s: %s", user_id, e)


_turso_service_instance: TursoMemoryService | None = None


def get_turso_memory_service() -> TursoMemoryService:
    """Return the global TursoMemoryService singleton."""
    global _turso_service_instance
    if _turso_service_instance is None:
        _turso_service_instance = TursoMemoryService()
    return _turso_service_instance

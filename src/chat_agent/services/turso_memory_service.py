"""Turso / libSQL Personal AI Memory & User Preferences Engine for Aryhant."""
from __future__ import annotations

import asyncio
import json
import logging
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
        sync_url: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self.db_path: str = db_path if db_path is not None else str(settings.resolved_turso_db_path)
        self.sync_url: str = sync_url if sync_url is not None else settings.turso_database_url
        self.auth_token: str = auth_token if auth_token is not None else settings.turso_auth_token
        self._write_lock = threading.Lock()

    def _sync_remote(self, conn: Any, stage: str = "write") -> None:
        """Synchronize local embedded replica with remote Turso database."""
        if hasattr(conn, "sync") and self.sync_url:
            try:
                conn.sync()
                logger.info("Turso remote sync (%s) completed successfully.", stage)
            except Exception as sync_err:
                logger.warning("Turso remote sync (%s) warning: %s.", stage, sync_err)

    def _get_connection(self, sync_on_read: bool = False) -> Any:
        """Obtain a database connection with embedded replica sync or fail loud if misconfigured."""
        if self.sync_url and (
            self.sync_url.startswith("libsql://")
            or self.sync_url.startswith("https://")
            or self.sync_url.startswith("http://")
        ):
            try:
                import libsql
            except ImportError as err:
                logger.critical("ARYHANT_TURSO_DATABASE_URL is set (%s), but 'libsql' is not installed.", self.sync_url)
                raise RuntimeError(
                    "ARYHANT_TURSO_DATABASE_URL is set but 'libsql' package is not installed. "
                    "Install it with `pip install libsql`."
                ) from err

            try:
                conn = libsql.connect(
                    self.db_path,
                    sync_url=self.sync_url,
                    auth_token=self.auth_token,
                    isolation_level=None,
                )
                try:
                    conn.execute("PRAGMA foreign_keys = ON;")
                except Exception:
                    pass
                if sync_on_read:
                    self._sync_remote(conn, stage="read")
                return conn
            except Exception as exc:
                logger.warning(
                    "Turso remote connection error (%s): %s. Falling back to local embedded replica.",
                    self.sync_url,
                    exc,
                )
                conn = sqlite3.connect(self.db_path, isolation_level=None)
                try:
                    conn.execute("PRAGMA foreign_keys = ON;")
                except Exception:
                    pass
                return conn

        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            pass
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
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error("Error updating user profile for %s: %s", user_id, exc)
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
        except Exception as exc:
            logger.warning("Failed to obtain DB connection for %s memory context: %s", user_id, exc)
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
        except Exception as exc:
            logger.warning("Error fetching memory context for %s: %s", user_id, exc)
            return default_context
        finally:
            try:
                conn.close()
            except Exception:
                pass

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
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error("Failed to add manual preference for %s: %s", user_id, exc)
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
                    except Exception:
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
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error("Error in remember_pattern for %s: %s", user_id, exc)
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
        except Exception as exc:
            logger.error("Error listing memories for %s: %s", user_id, exc)
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
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error("Error deleting memory %s for %s: %s", memory_id, user_id, exc)
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
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error("Error clearing memories for %s: %s", user_id, exc)
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
            if provider == "nebius" and getattr(settings, "NEBIUS_API_KEY", ""):
                import openai
                client = openai.AsyncOpenAI(
                    base_url=getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
                    api_key=settings.nebius_api_key,
                )
                resp = await client.chat.completions.create(
                    model=getattr(settings, "NEBIUS_QUESTION_MODEL", "nvidia/Nemotron-3-Nano-30B-A3B"),
                    messages=[{"role": "user", "content": distill_prompt}],
                    temperature=0.2,
                    max_tokens=256,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content or ""
                try:
                    extracted = json.loads(content)
                except Exception:
                    match = re.search(r"\{.*?\}", content, re.DOTALL)
                    if match:
                        extracted = json.loads(match.group(0))
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
                except Exception:
                    match = re.search(r"\{.*?\}", text_out, re.DOTALL)
                    if match:
                        extracted = json.loads(match.group(0))

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
        except Exception as exc:
            logger.warning("Background memory extraction notice for %s: %s", user_id, exc)


_turso_service_instance: TursoMemoryService | None = None


def get_turso_memory_service() -> TursoMemoryService:
    """Return the global TursoMemoryService singleton."""
    global _turso_service_instance
    if _turso_service_instance is None:
        _turso_service_instance = TursoMemoryService()
    return _turso_service_instance

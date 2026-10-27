from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from chat_agent.config import settings

logger = logging.getLogger(__name__)


async def execute_code_in_sandbox(
    code: str,
    language: str = "python",
    image: str = "python:3.12-slim",
    timeout_sec: float = 30.0,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Execute code in an isolated Nebius microVM sandbox and return output."""
    key = api_key if api_key is not None else (getattr(settings, "NEBIUS_API_KEY", "") or "")
    clean_code = code.strip()
    if not clean_code:
        return {
            "status": "skipped",
            "reason": "empty code",
            "stdout": "",
            "stderr": "No code provided to execute.",
            "exit_code": -1,
            "duration_sec": 0.0,
        }

    start_time = time.time()

    # Strategy 1: Attempt official contree-sdk if available
    try:
        from contree_sdk import Contree  # type: ignore[import-untyped]

        client = Contree()
        img = await client.images.use(image)
        shell_cmd = f"python3 -c {clean_code!r}" if language == "python" else clean_code
        res = await img.run(shell=shell_cmd, disposable=True)
        duration = round(time.time() - start_time, 3)
        return {
            "status": "success" if res.exit_code == 0 else "failed",
            "reason": f"exit code {res.exit_code}",
            "stdout": str(res.stdout or ""),
            "stderr": str(res.stderr or ""),
            "exit_code": int(res.exit_code),
            "duration_sec": duration,
        }
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("contree-sdk sandbox execution failed (%s); trying REST fallback.", exc)

    # Strategy 2: Nebius TokenFactory Sandboxes REST API
    if not key:
        logger.info("NEBIUS_API_KEY unconfigured; skipping Nebius sandbox execution.")
        return {
            "status": "skipped",
            "reason": "NEBIUS_API_KEY unconfigured",
            "stdout": "",
            "stderr": "Nebius sandbox execution skipped: NEBIUS_API_KEY unconfigured.",
            "exit_code": 0,
            "duration_sec": round(time.time() - start_time, 3),
        }

    base_url = getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/")
    sandbox_url = f"{base_url}/sandboxes/execute"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    project_id = getattr(settings, "NEBIUS_PROJECT_ID", "") or ""
    if project_id:
        headers["X-Project-Id"] = project_id

    payload: dict[str, Any] = {
        "image": image,
        "language": language,
        "code": clean_code,
        "timeout": timeout_sec,
    }

    async with httpx.AsyncClient(timeout=timeout_sec + 5.0) as http_client:
        try:
            resp = await http_client.post(sandbox_url, headers=headers, json=payload)
            duration = round(time.time() - start_time, 3)
            if resp.status_code == 200:
                data = resp.json()
                ec = int(data.get("exit_code", 0))
                return {
                    "status": "success" if ec == 0 else "failed",
                    "reason": f"exit code {ec}",
                    "stdout": str(data.get("stdout") or ""),
                    "stderr": str(data.get("stderr") or ""),
                    "exit_code": ec,
                    "duration_sec": duration,
                }
            logger.warning("Nebius sandbox REST endpoint returned HTTP %d: %s", resp.status_code, resp.text)
            return {
                "status": "error",
                "reason": f"HTTP {resp.status_code}",
                "stdout": "",
                "stderr": f"Sandbox HTTP {resp.status_code}: {resp.text[:200]}",
                "exit_code": -1,
                "duration_sec": duration,
            }
        except Exception as rest_err:
            duration = round(time.time() - start_time, 3)
            logger.warning("Nebius sandbox REST invocation error: %s", rest_err)
            return {
                "status": "error",
                "reason": type(rest_err).__name__,
                "stdout": "",
                "stderr": str(rest_err),
                "exit_code": -1,
                "duration_sec": duration,
            }

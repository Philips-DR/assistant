"""Tell someone when a long job finishes.

The only module in the server that knows a tool by name, the way tools.yaml is the only file
that knows every tool exists. Everything else stays tool-agnostic; if a new tool needs
watching, it gets a watcher here and nowhere else.

It polls through the registry directly rather than through `session.execute`: this is the
server looking, not anyone acting, so it is neither audited nor gated.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from assistant.tools import ToolRegistry

POLL_SECONDS = 15
FINISHED = {"done", "failed", "interrupted"}

Emit = Callable[[dict[str, Any]], Awaitable[None]]


async def _read(registry: ToolRegistry, name: str) -> dict[str, Any] | None:
    tool = registry.find(name)
    if tool is None:
        return None
    outcome = await registry.call(tool, {})
    if outcome.is_error:
        return None
    try:
        return json.loads(outcome.text)
    except json.JSONDecodeError:
        return None


def transcription_notice(before: str | None, job: dict[str, Any] | None) -> dict[str, Any] | None:
    """What to say when a job changes state, or None. Pure, so it can be tested alone."""
    if not job or before != "running" or job.get("state") not in FINISHED:
        return None
    name = Path(str(job.get("audio", ""))).name
    state = job["state"]
    if state == "done":
        return {"level": "success", "title": "Transcript ready",
                "body": f"{name} is transcribed. Notes can be written from it now."}
    if state == "failed":
        return {"level": "error", "title": "Transcription failed",
                "body": f"{name}: {str(job.get('detail', ''))[:200]}"}
    return {"level": "warning", "title": "Transcription interrupted",
            "body": f"{name} stopped before finishing. Starting it again resumes where it left off."}


def recording_notice(before: str | None, session: dict[str, Any] | None) -> dict[str, Any] | None:
    if before == "recording" and session and session.get("state") == "orphaned":
        return {"level": "warning", "title": "Recording interrupted",
                "body": f"{session.get('id')} stopped unexpectedly. Its audio is safe -- stop it to recover."}
    return None


async def watch(registry: ToolRegistry, emit: Emit) -> None:
    """Run until cancelled. A failed poll is skipped, never fatal."""
    job_state: dict[str, str] = {}
    recording: str | None = None
    while True:
        try:
            status = await _read(registry, "meet_ai__transcription_status")
            job = (status or {}).get("job")
            if job:
                notice = transcription_notice(job_state.get(job["id"]), job)
                job_state[job["id"]] = job["state"]
                if notice:
                    await emit({"type": "notice", **notice})

            rec = await _read(registry, "meet_ai__recording_status")
            session = (rec or {}).get("session")
            notice = recording_notice(recording, session)
            recording = session.get("state") if session else None
            if notice:
                await emit({"type": "notice", **notice})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # the next poll will try again
        await asyncio.sleep(POLL_SECONDS)


# ---------------------------------------------------------------------------
# The model login
# ---------------------------------------------------------------------------

LOGIN_POLL_SECONDS = 600


def login_notice(before: str | None, status: dict[str, Any]) -> dict[str, Any] | None:
    """Announce the model login going bad, once. The SSO access token renews itself from a
    refresh token, so a countdown to its expiry time would be wrong; the honest signal is
    the moment a live check first fails."""
    if status.get("level") == "error" and before != "error":
        return {"level": "error", "title": "AWS login needs renewing",
                "body": status.get("hint") or str(status.get("detail", ""))[:200]}
    if status.get("level") == "ok" and before == "error":
        return {"level": "success", "title": "AWS login working again",
                "body": "Notes and minutes can be written."}
    return None


async def watch_login(config: Any, emit: Emit) -> None:
    from assistant.status import model_status

    level: str | None = None
    while True:
        try:
            status = await asyncio.to_thread(model_status, config)
            notice = login_notice(level, status)
            level = status.get("level")
            if notice:
                await emit({"type": "notice", **notice})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(LOGIN_POLL_SECONDS)

"""In-memory store for paused RunState plus approval interruption metadata.

When a tool call needs human approval, the SDK pauses the run and surfaces
`interruptions` on the streaming result. We serialize the `RunState` with
`state.to_json()` and stash it (together with the agent reference) under a
session id so the `/chat/confirm` endpoint can resume it later.
"""
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from agents import Agent

logger = logging.getLogger(__name__)

PENDING_TTL_SEC = 600


@dataclass
class PendingRun:
    session_id: str
    agent: Agent
    state_json: dict[str, Any]
    interruption_tool_name: str
    interruption_tool_args: dict[str, Any]
    created_at: float


_store: dict[str, PendingRun] = {}

# Tracks whether the agent has already taken a safety backup for a
# given chat session. Keyed by session id; the stored dict is the
# backup metadata returned by `app.ai.backup.create_backup`.
_session_backups: dict[str, dict] = {}
_SESSION_BACKUP_TTL_SEC = 86400  # drop bookkeeping after 24h


def create_session_id() -> str:
    return str(uuid.uuid4())


def _cleanup_expired_backups() -> None:
    now = time.time()
    expired = [
        sid for sid, info in _session_backups.items()
        if now - float(info.get("_tracked_at", 0)) > _SESSION_BACKUP_TTL_SEC
    ]
    for sid in expired:
        _session_backups.pop(sid, None)


def get_session_backup(session_id: str) -> dict | None:
    """Return backup metadata previously recorded for this session, if any."""
    _cleanup_expired_backups()
    return _session_backups.get(session_id)


def set_session_backup(session_id: str, info: dict) -> None:
    """Record that a safety backup has been taken for this session."""
    _cleanup_expired_backups()
    enriched = dict(info)
    enriched["_tracked_at"] = time.time()
    _session_backups[session_id] = enriched


def _cleanup_expired() -> None:
    now = time.time()
    expired = [
        sid for sid, pr in _store.items() if now - pr.created_at > PENDING_TTL_SEC
    ]
    for sid in expired:
        _store.pop(sid, None)


def store_pending(
    session_id: str,
    agent: Agent,
    state_json: dict[str, Any],
    tool_name: str,
    tool_args: dict[str, Any],
) -> None:
    _cleanup_expired()
    _store[session_id] = PendingRun(
        session_id=session_id,
        agent=agent,
        state_json=state_json,
        interruption_tool_name=tool_name,
        interruption_tool_args=tool_args,
        created_at=time.time(),
    )


def get_pending(session_id: str) -> PendingRun | None:
    _cleanup_expired()
    return _store.get(session_id)


def remove_pending(session_id: str) -> None:
    _store.pop(session_id, None)

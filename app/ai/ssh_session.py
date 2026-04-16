"""In-memory cache of SSH-unlocked chat sessions.

When the admin enters the correct SSH PIN via the chat UI, we cache the
raw PIN in process memory, keyed by chat session id, for a short TTL.
The cached PIN is then used by `ssh_run_command` to decrypt the per-node
stored credentials (`NodeSSHCredentials`) on demand.

Rationale:
    - The SDK's tool handlers cannot interactively prompt the user.
    - Storing the PIN on disk would defeat its whole point.
    - A per-session in-memory cache with a hard TTL strikes the balance
      between UX ("don't re-ask on every command") and safety
      ("don't persist credentials").

The PIN is never serialized, logged, or exposed via any API.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Matches the expected user workflow (diagnose, fix, verify). Long
# enough to avoid nagging re-prompts, short enough that forgotten
# sessions don't linger. Renewed every time we read a valid entry.
SSH_UNLOCK_TTL_SEC = 30 * 60


@dataclass
class _UnlockEntry:
    pin: str
    expires_at: float


_store: dict[str, _UnlockEntry] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _prune_locked() -> None:
    now = _now()
    expired = [sid for sid, entry in _store.items() if entry.expires_at <= now]
    for sid in expired:
        _store.pop(sid, None)


def unlock_session(session_id: str, pin: str) -> None:
    """Cache the raw PIN for `session_id` for `SSH_UNLOCK_TTL_SEC`."""
    if not session_id:
        raise ValueError("session_id is required")
    if not pin:
        raise ValueError("pin is required")
    with _lock:
        _prune_locked()
        _store[session_id] = _UnlockEntry(
            pin=pin, expires_at=_now() + SSH_UNLOCK_TTL_SEC
        )
    logger.debug("SSH session unlocked: %s", session_id)


def get_unlocked_pin(session_id: str) -> str | None:
    """Return the cached PIN if still valid, else None.

    Valid reads extend the TTL (sliding window) so an active admin
    session won't get locked out mid-diagnosis.
    """
    if not session_id:
        return None
    with _lock:
        _prune_locked()
        entry = _store.get(session_id)
        if not entry:
            return None
        entry.expires_at = _now() + SSH_UNLOCK_TTL_SEC
        return entry.pin


def is_session_unlocked(session_id: str) -> bool:
    return get_unlocked_pin(session_id) is not None


def lock_session(session_id: str) -> bool:
    """Explicitly drop the PIN for a session. Returns True if one existed."""
    if not session_id:
        return False
    with _lock:
        return _store.pop(session_id, None) is not None


def get_ttl_seconds(session_id: str) -> int:
    """Return remaining TTL for the session, or 0 if not unlocked."""
    if not session_id:
        return 0
    with _lock:
        _prune_locked()
        entry = _store.get(session_id)
        if not entry:
            return 0
        remaining = int(entry.expires_at - _now())
        return max(remaining, 0)

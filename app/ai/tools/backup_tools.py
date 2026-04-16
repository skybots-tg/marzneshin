"""Safety-backup tool exposed to the AI agent.

The agent is instructed (see `app.ai.agent.build_instructions`) to call
`create_session_backup` BEFORE any write operation. The tool is
idempotent per chat session — the first call creates a fresh DB dump,
subsequent calls within the same session return the same metadata.

Backups live for `BACKUP_RETENTION_DAYS` days and are cleaned up by
a scheduled task (`app.tasks.ai_backups_cleanup`).
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.ai.backup import BACKUP_RETENTION_DAYS, create_backup
from app.ai.session_context import get_current_session_id
from app.ai.state_store import get_session_backup, set_session_backup
from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="create_session_backup",
    description=(
        "Create a safety backup of the Marzneshin database for the current "
        "chat session. MANDATORY: you MUST call this tool before any write "
        "operation (any tool marked [REQUIRES CONFIRMATION]). The backup is "
        "taken at most once per session — calling this tool again in the same "
        "session returns the existing backup metadata without creating a new "
        f"file. Backups live for {BACKUP_RETENTION_DAYS} days and are then "
        "auto-deleted. If the backup fails, DO NOT proceed with the write "
        "operation — report the error to the admin instead."
    ),
    requires_confirmation=False,
)
async def create_session_backup(db: Session) -> dict:
    session_id = get_current_session_id()
    if not session_id:
        return {
            "error": (
                "Session id is not available; cannot guarantee one-backup-"
                "per-session semantics. Aborting to avoid duplicates."
            ),
        }

    existing = get_session_backup(session_id)
    if existing:
        payload = {k: v for k, v in existing.items() if not k.startswith("_")}
        return {
            "success": True,
            "reused": True,
            "message": "Safety backup already exists for this session.",
            "backup": payload,
        }

    try:
        # create_backup() does blocking I/O (sqlite3 backup / subprocess);
        # hand it to a worker thread so the event loop is not blocked for
        # installs with large databases.
        info = await asyncio.to_thread(create_backup)
    except Exception as exc:
        logger.exception("AI safety backup failed")
        return {
            "error": f"Failed to create backup: {exc}",
            "reused": False,
        }

    payload = info.to_dict()
    set_session_backup(session_id, payload)
    logger.info(
        "AI safety backup created: session=%s path=%s size=%d",
        session_id, payload["path"], payload["size_bytes"],
    )
    return {
        "success": True,
        "reused": False,
        "message": (
            f"Safety backup created ({info.dialect}). Will be retained "
            f"for {BACKUP_RETENTION_DAYS} days."
        ),
        "backup": payload,
    }

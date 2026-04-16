"""Scheduled cleanup of AI agent safety backups.

The AI assistant takes a DB snapshot before its first write in each
chat session (see `app.ai.backup`). We keep those snapshots for a
week — afterwards they're stale and should be removed to avoid
filling the disk on busy installs.
"""
from __future__ import annotations

import asyncio
import logging

from app.ai.backup import cleanup_old_backups

logger = logging.getLogger(__name__)


async def cleanup_ai_backups() -> None:
    """Remove AI-agent backups older than the retention window."""
    try:
        # File I/O — keep it off the event loop.
        result = await asyncio.to_thread(cleanup_old_backups)
    except Exception:
        logger.exception("AI backup cleanup failed")
        return

    if result.get("deleted") or result.get("errors"):
        logger.info("AI backup cleanup result: %s", result)

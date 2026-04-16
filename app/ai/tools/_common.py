"""Shared helpers for AI tools.

Keeps safety-related constants and tiny utilities in one place so
individual tool files stay focused on domain logic.

The agent is never supposed to be cut off from data — it just reads it
in pages. Every list-style tool clamps page size via `clamp_limit`,
and builds its response with `paginated_envelope` so the agent always
sees a uniform `{total, offset, limit, truncated, next_offset}` shape
and knows exactly how to request the next slice (mirrors Cursor's own
paged tool convention).
"""
from __future__ import annotations

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100


def clamp_limit(limit: int, default: int = DEFAULT_LIST_LIMIT, maximum: int = MAX_LIST_LIMIT) -> int:
    """Clamp a caller-supplied page size into a safe range.

    - Non-positive values fall back to `default`.
    - Values above `maximum` are hard-capped.
    """
    if limit is None or limit <= 0:
        return default
    if limit > maximum:
        return maximum
    return int(limit)


def clamp_offset(offset: int) -> int:
    if offset is None or offset < 0:
        return 0
    return int(offset)


def paginated_envelope(total: int, offset: int, limit: int) -> dict:
    """Build the standard pagination envelope for list tools.

    The agent reads `truncated` to decide whether to fetch more and
    `next_offset` to know exactly which `offset` to pass next time.
    When the page is complete, `next_offset` is `None` — the agent
    should not call again for more.
    """
    truncated = total > offset + limit
    return {
        "total": int(total),
        "offset": int(offset),
        "limit": int(limit),
        "truncated": truncated,
        "next_offset": (offset + limit) if truncated else None,
    }

"""Shared helpers for AI tools.

Keeps safety-related constants and tiny utilities in one place so
individual tool files stay focused on domain logic. All public list
tools should pass their incoming `limit` through `clamp_limit` to avoid
dumping the entire table (e.g. 10k+ users) into a single tool result.
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

"""ContextVar plumbing for the current AI chat session.

The Agents SDK invokes tool handlers inside tasks spawned by
`Runner.run_streamed`. asyncio propagates the calling context into
those tasks, so a ContextVar set before the run is visible inside
every tool handler — without having to thread `session_id` through
every handler signature.

Usage:
    token = set_current_session_id(session_id)
    try:
        result = Runner.run_streamed(agent, input=...)
        ...
    finally:
        reset_current_session_id(token)
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_current_session_id: ContextVar[Optional[str]] = ContextVar(
    "marzneshin_ai_session_id", default=None
)


def set_current_session_id(session_id: str) -> Token:
    return _current_session_id.set(session_id)


def reset_current_session_id(token: Token) -> None:
    _current_session_id.reset(token)


def get_current_session_id() -> Optional[str]:
    return _current_session_id.get()

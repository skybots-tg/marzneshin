import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.ai.models import (
    ChatMessage,
    ConfirmAction,
    PendingConfirmation,
    ToolCall,
    ToolResult,
)
from app.ai.tool_registry import get_tool

logger = logging.getLogger(__name__)

PENDING_TTL = 300

_pending_confirmations: dict[str, PendingConfirmation] = {}
_pending_timestamps: dict[str, float] = {}


def _cleanup_expired():
    now = time.time()
    expired = [sid for sid, ts in _pending_timestamps.items() if now - ts > PENDING_TTL]
    for sid in expired:
        _pending_confirmations.pop(sid, None)
        _pending_timestamps.pop(sid, None)


def create_session_id() -> str:
    return str(uuid.uuid4())


async def execute_tool(
    tool_call: ToolCall,
    db: Session,
) -> ToolResult:
    tool_name = tool_call.function.name
    entry = get_tool(tool_name)
    if not entry:
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

    try:
        args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError as e:
        return ToolResult(success=False, error=f"Invalid arguments JSON: {str(e)}")

    handler = entry["handler"]
    try:
        result = await handler(db=db, **args)
        return ToolResult(success=True, data=result)
    except Exception as e:
        logger.exception("Tool %s execution failed", tool_name)
        return ToolResult(success=False, error=str(e))


def requires_confirmation(tool_call: ToolCall) -> bool:
    entry = get_tool(tool_call.function.name)
    if not entry:
        return False
    return entry["definition"].requires_confirmation


def store_pending(
    session_id: str,
    tool_call: ToolCall,
    messages: list[ChatMessage],
    model: str,
) -> PendingConfirmation:
    _cleanup_expired()

    try:
        args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        args = {}

    entry = get_tool(tool_call.function.name)
    description = entry["definition"].description if entry else tool_call.function.name

    pending = PendingConfirmation(
        session_id=session_id,
        tool_call=tool_call,
        tool_name=tool_call.function.name,
        tool_args=args,
        description=description,
        messages_snapshot=messages,
        model=model,
    )
    _pending_confirmations[session_id] = pending
    _pending_timestamps[session_id] = time.time()
    return pending


def get_pending(session_id: str) -> PendingConfirmation | None:
    _cleanup_expired()
    return _pending_confirmations.get(session_id)


def remove_pending(session_id: str) -> None:
    _pending_confirmations.pop(session_id, None)
    _pending_timestamps.pop(session_id, None)


def build_rejection_message(pending: PendingConfirmation) -> str:
    return (
        f"The user rejected the tool call '{pending.tool_name}' "
        f"with arguments {json.dumps(pending.tool_args)}. "
        f"Do not retry this action. Explain what you wanted to do and ask for guidance."
    )

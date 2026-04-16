import json
import logging
from typing import Any, AsyncIterator

from agents import RunState, Runner
from agents.exceptions import MaxTurnsExceeded
from agents.items import ToolApprovalItem
from agents.result import RunResultStreaming
from agents.stream_events import (
    RawResponsesStreamEvent,
    RunItemStreamEvent,
)
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai.types.responses import ResponseTextDeltaEvent
from sqlalchemy.orm import Session

from app.ai.agent import build_agent
from app.ai.models import (
    ChatMessage,
    ChatRequest,
    ConfirmAction,
    ConfirmRequest,
    MessageRole,
)
from app.ai.openai_client import list_models
from app.ai.session_context import (
    reset_current_session_id,
    set_current_session_id,
)
from app.ai.state_store import (
    create_session_id,
    get_pending,
    remove_pending,
    store_pending,
)
from app.ai.tool_registry import get_all_tools
from app.db.models import Settings
from app.dependencies import DBDep, SudoAdminDep
from app.models.settings import AISettings, AISettingsResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Assistant"])

MAX_TURNS = 20


def _get_ai_settings(db: Session) -> AISettings:
    row = db.query(Settings).first()
    if not row or not row.ai:
        return AISettings()
    return AISettings(**row.ai)


def _require_api_key(settings: AISettings) -> str:
    if not settings.api_key:
        raise HTTPException(
            status_code=400,
            detail="OpenAI API key is not configured. Set it in AI settings.",
        )
    return settings.api_key


@router.get("/settings", response_model=AISettingsResponse)
def get_ai_settings(db: DBDep, admin: SudoAdminDep):
    s = _get_ai_settings(db)
    return AISettingsResponse(
        configured=bool(s.api_key),
        default_model=s.default_model,
        thinking_model=s.thinking_model,
        max_tokens=s.max_tokens,
        temperature=s.temperature,
        reasoning_effort=s.reasoning_effort,
        system_prompt=s.system_prompt,
    )


@router.put("/settings", response_model=AISettingsResponse)
def update_ai_settings(db: DBDep, body: AISettings, admin: SudoAdminDep):
    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    # Preserve existing api_key when client sends an empty value.
    # Empty string means "don't change the key", not "delete it".
    existing = AISettings(**settings.ai) if settings.ai else AISettings()
    effective_key = body.api_key or existing.api_key
    payload = body.model_copy(update={"api_key": effective_key})

    settings.ai = payload.model_dump(mode="json")
    db.commit()
    return AISettingsResponse(
        configured=bool(effective_key),
        default_model=payload.default_model,
        thinking_model=payload.thinking_model,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        reasoning_effort=payload.reasoning_effort,
        system_prompt=payload.system_prompt,
    )


@router.get("/models")
async def get_models(db: DBDep, admin: SudoAdminDep):
    s = _get_ai_settings(db)
    api_key = _require_api_key(s)
    db.close()
    try:
        models = await list_models(api_key)
        return {"models": [m.model_dump() for m in models]}
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"OpenAI API error: {str(e)}"
        )


@router.get("/tools")
def get_tools_list(admin: SudoAdminDep):
    tools = get_all_tools()
    return {
        "tools": [t.model_dump() for t in tools],
        "total": len(tools),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _messages_to_input_items(
    messages: list[ChatMessage],
) -> list[dict[str, Any]]:
    """Convert frontend ChatMessage list to Responses API input items."""
    items: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role in (MessageRole.system, MessageRole.developer):
            items.append({"role": "developer", "content": msg.content or ""})
            continue
        if msg.role == MessageRole.tool:
            items.append({
                "type": "function_call_output",
                "call_id": msg.tool_call_id or "",
                "output": msg.content or "",
            })
            continue
        if msg.role == MessageRole.assistant:
            if msg.content:
                items.append({"role": "assistant", "content": msg.content})
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    items.append({
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    })
            continue
        items.append({"role": "user", "content": msg.content or ""})
    return items


def _extract_tool_name(item: ToolApprovalItem) -> str:
    raw = getattr(item, "raw_item", None)
    if raw is None:
        return "unknown"
    return getattr(raw, "name", None) or "unknown"


def _extract_tool_args(item: ToolApprovalItem) -> dict[str, Any]:
    raw = getattr(item, "raw_item", None)
    arguments = getattr(raw, "arguments", "") if raw else ""
    if not arguments:
        return {}
    try:
        return json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {}


async def _stream_run(
    result: RunResultStreaming,
    session_id: str,
    agent_for_resume,
) -> AsyncIterator[str]:
    """Stream SDK events as SSE using the legacy protocol."""
    try:
        async for event in result.stream_events():
            if isinstance(event, RawResponsesStreamEvent):
                if isinstance(event.data, ResponseTextDeltaEvent):
                    yield _sse("content", {"text": event.data.delta})
                continue

            if isinstance(event, RunItemStreamEvent):
                item = event.item
                name = event.name

                if name == "tool_called":
                    raw = getattr(item, "raw_item", None)
                    tool_name = getattr(raw, "name", "") if raw else ""
                    call_id = (
                        getattr(raw, "call_id", "") if raw else ""
                    ) or getattr(item, "id", "")
                    arguments = getattr(raw, "arguments", "") if raw else ""
                    yield _sse(
                        "tool_call",
                        {
                            "tool_call_id": call_id or "",
                            "name": tool_name or "",
                            "arguments": arguments or "",
                            "requires_confirmation": False,
                        },
                    )
                elif name == "tool_output":
                    raw = getattr(item, "raw_item", None)
                    if isinstance(raw, dict):
                        call_id = raw.get("call_id", "") or ""
                    else:
                        call_id = getattr(raw, "call_id", "") or ""
                    output = getattr(item, "output", "")
                    if not isinstance(output, str):
                        output = json.dumps(output, default=str)
                    yield _sse(
                        "tool_result",
                        {
                            "tool_call_id": call_id,
                            "name": "",
                            "result": output,
                        },
                    )
    except MaxTurnsExceeded:
        yield _sse(
            "error",
            {
                "message": (
                    f"Run exceeded {MAX_TURNS} turns without producing a final "
                    "answer. Try rephrasing your request more specifically."
                )
            },
        )
        return
    except Exception as e:
        logger.exception("Agent streaming error")
        yield _sse("error", {"message": f"Agent error: {str(e)}"})
        return

    if result.interruptions:
        interruption = result.interruptions[0]
        if isinstance(interruption, ToolApprovalItem):
            tool_name = _extract_tool_name(interruption)
            tool_args = _extract_tool_args(interruption)
            state = result.to_state()
            store_pending(
                session_id=session_id,
                agent=agent_for_resume,
                state_json=state.to_json(),
                tool_name=tool_name,
                tool_args=tool_args,
            )
            yield _sse(
                "pending_confirmation",
                {
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                },
            )
            return

    yield _sse("done", {"session_id": session_id})


@router.post("/chat")
async def chat(body: ChatRequest, db: DBDep, admin: SudoAdminDep):
    ai_settings = _get_ai_settings(db)
    api_key = _require_api_key(ai_settings)
    db.close()

    model = body.model or ai_settings.default_model
    session_id = body.session_id or create_session_id()

    agent = build_agent(
        api_key=api_key,
        model_name=model,
        system_prompt=ai_settings.system_prompt,
        max_tokens=ai_settings.max_tokens,
        temperature=ai_settings.temperature,
        reasoning_effort=ai_settings.reasoning_effort,
    )

    input_items = _messages_to_input_items(body.messages)

    async def event_stream():
        token = set_current_session_id(session_id)
        try:
            try:
                result = Runner.run_streamed(
                    agent,
                    input=input_items,
                    max_turns=MAX_TURNS,
                )
            except Exception as e:
                logger.exception("Failed to start agent run")
                yield _sse("error", {"message": f"Agent error: {str(e)}"})
                return

            async for chunk in _stream_run(result, session_id, agent):
                yield chunk
        finally:
            reset_current_session_id(token)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )


@router.post("/chat/confirm")
async def confirm_action(body: ConfirmRequest, db: DBDep, admin: SudoAdminDep):
    ai_settings = _get_ai_settings(db)
    _require_api_key(ai_settings)
    db.close()

    pending = get_pending(body.session_id)
    if not pending:
        raise HTTPException(
            status_code=404,
            detail="No pending confirmation found for this session",
        )

    agent = pending.agent
    state_json = pending.state_json
    remove_pending(body.session_id)

    async def event_stream():
        token = set_current_session_id(body.session_id)
        try:
            try:
                state = await RunState.from_json(agent, state_json)
            except Exception as e:
                logger.exception("Failed to deserialize paused run state")
                yield _sse(
                    "error",
                    {"message": f"Failed to resume paused run: {str(e)}"},
                )
                return

            interruptions = state.get_interruptions()
            for interruption in interruptions:
                if not isinstance(interruption, ToolApprovalItem):
                    continue
                if body.action == ConfirmAction.approve:
                    state.approve(interruption)
                else:
                    state.reject(interruption)

            try:
                result = Runner.run_streamed(agent, state, max_turns=MAX_TURNS)
            except Exception as e:
                logger.exception("Failed to resume agent run")
                yield _sse("error", {"message": f"Agent error: {str(e)}"})
                return

            async for chunk in _stream_run(result, body.session_id, agent):
                yield chunk
        finally:
            reset_current_session_id(token)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

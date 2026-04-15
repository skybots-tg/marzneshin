import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai import tools as _tools_import  # noqa: F401 — register all tools
from app.ai.models import (
    ChatRequest,
    ConfirmRequest,
    ConfirmAction,
    ToolCall,
    ToolResult,
)
from app.ai.openai_client import (
    build_instructions,
    convert_messages_to_input,
    list_models,
    stream_response,
)
from app.ai.tool_executor import (
    create_session_id,
    execute_tool,
    get_pending,
    remove_pending,
    requires_confirmation,
    store_pending,
    build_rejection_message,
)
from app.ai.tool_registry import get_all_tools, get_openai_tools_schema
from app.db import GetDB
from app.db.models import Settings
from app.dependencies import DBDep, SudoAdminDep
from app.models.settings import AISettings, AISettingsResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Assistant"])

_TOOL_KEEPALIVE_SEC = 10.0


async def _stream_tool_with_keepalive(tc: ToolCall):
    """Yield SSE comment lines while waiting; last value is the ToolResult."""
    with GetDB() as tool_db:
        task = asyncio.create_task(execute_tool(tc, tool_db))
        while not task.done():
            done, _ = await asyncio.wait(
                {task}, timeout=_TOOL_KEEPALIVE_SEC
            )
            if task in done:
                break
            yield ": keepalive\n\n"
        yield await task


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
    settings.ai = body.model_dump(mode="json")
    db.commit()
    return AISettingsResponse(
        configured=bool(body.api_key),
        default_model=body.default_model,
        thinking_model=body.thinking_model,
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        reasoning_effort=body.reasoning_effort,
        system_prompt=body.system_prompt,
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


@router.post("/chat")
async def chat(body: ChatRequest, db: DBDep, admin: SudoAdminDep):
    ai_settings = _get_ai_settings(db)
    api_key = _require_api_key(ai_settings)
    db.close()

    model = body.model or ai_settings.default_model
    session_id = body.session_id or create_session_id()

    instructions = build_instructions(ai_settings.system_prompt)
    tools = get_openai_tools_schema()
    input_items = convert_messages_to_input(body.messages)

    async def event_stream():
        nonlocal input_items
        max_iterations = 10

        for iteration in range(max_iterations):
            tool_calls_result = []
            has_tool_calls = False
            output_items = []

            try:
                async for chunk in stream_response(
                    api_key=api_key,
                    input_items=input_items,
                    instructions=instructions,
                    model=model,
                    tools=tools,
                    max_tokens=ai_settings.max_tokens,
                    temperature=ai_settings.temperature,
                    reasoning_effort=ai_settings.reasoning_effort,
                ):
                    if chunk["type"] == "content":
                        yield _sse("content", {"text": chunk["content"]})
                    elif chunk["type"] == "tool_calls":
                        tool_calls_result = chunk["tool_calls"]
                        has_tool_calls = True
                    elif chunk["type"] == "done":
                        output_items = chunk.get("output_items", [])
            except Exception as e:
                logger.exception("OpenAI streaming error")
                yield _sse("error", {"message": f"OpenAI error: {str(e)}"})
                return

            if not has_tool_calls:
                yield _sse("done", {"session_id": session_id})
                return

            input_items.extend(output_items)

            all_auto = True
            for tc in tool_calls_result:
                if requires_confirmation(tc):
                    all_auto = False
                    yield _sse("tool_call", {
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                        "requires_confirmation": True,
                    })

                    store_pending(session_id, tc, input_items, model)

                    yield _sse("pending_confirmation", {
                        "session_id": session_id,
                        "tool_name": tc.function.name,
                        "tool_args": json.loads(tc.function.arguments),
                    })
                    return
                else:
                    yield _sse("tool_call", {
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                        "requires_confirmation": False,
                    })

                    result: ToolResult | None = None
                    async for _piece in _stream_tool_with_keepalive(tc):
                        if isinstance(_piece, ToolResult):
                            result = _piece
                        else:
                            yield _piece

                    assert result is not None
                    result_str = json.dumps(
                        result.data if result.success else {"error": result.error},
                        default=str,
                    )
                    yield _sse("tool_result", {
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "result": result_str,
                    })

                    input_items.append({
                        "type": "function_call_output",
                        "call_id": tc.id,
                        "output": result_str,
                    })

            if not all_auto:
                return

        yield _sse("done", {"session_id": session_id})

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
    api_key = _require_api_key(ai_settings)
    db.close()

    pending = get_pending(body.session_id)
    if not pending:
        raise HTTPException(
            status_code=404,
            detail="No pending confirmation found for this session",
        )

    input_items = list(pending.input_snapshot)
    model = pending.model
    tc = pending.tool_call
    remove_pending(body.session_id)

    instructions = build_instructions(ai_settings.system_prompt)
    tools = get_openai_tools_schema()

    if body.action == ConfirmAction.reject:
        rejection = build_rejection_message(pending)
        input_items.append({
            "type": "function_call_output",
            "call_id": tc.id,
            "output": json.dumps({"rejected": True, "message": rejection}),
        })
    else:
        with GetDB() as tool_db:
            result = await execute_tool(tc, tool_db)

        result_str = json.dumps(
            result.data if result.success else {"error": result.error},
            default=str,
        )
        input_items.append({
            "type": "function_call_output",
            "call_id": tc.id,
            "output": result_str,
        })

    async def event_stream():
        nonlocal input_items
        max_iterations = 10

        for iteration in range(max_iterations):
            tool_calls_result = []
            has_tool_calls = False
            output_items = []

            try:
                async for chunk in stream_response(
                    api_key=api_key,
                    input_items=input_items,
                    instructions=instructions,
                    model=model,
                    tools=tools,
                    max_tokens=ai_settings.max_tokens,
                    temperature=ai_settings.temperature,
                    reasoning_effort=ai_settings.reasoning_effort,
                ):
                    if chunk["type"] == "content":
                        yield _sse("content", {"text": chunk["content"]})
                    elif chunk["type"] == "tool_calls":
                        tool_calls_result = chunk["tool_calls"]
                        has_tool_calls = True
                    elif chunk["type"] == "done":
                        output_items = chunk.get("output_items", [])
            except Exception as e:
                logger.exception("OpenAI streaming error on confirm")
                yield _sse("error", {"message": f"OpenAI error: {str(e)}"})
                return

            if not has_tool_calls:
                yield _sse("done", {"session_id": body.session_id})
                return

            input_items.extend(output_items)

            for tc_new in tool_calls_result:
                if requires_confirmation(tc_new):
                    yield _sse("tool_call", {
                        "tool_call_id": tc_new.id,
                        "name": tc_new.function.name,
                        "arguments": tc_new.function.arguments,
                        "requires_confirmation": True,
                    })
                    store_pending(
                        body.session_id, tc_new, input_items, model
                    )
                    yield _sse("pending_confirmation", {
                        "session_id": body.session_id,
                        "tool_name": tc_new.function.name,
                        "tool_args": json.loads(tc_new.function.arguments),
                    })
                    return
                else:
                    yield _sse("tool_call", {
                        "tool_call_id": tc_new.id,
                        "name": tc_new.function.name,
                        "arguments": tc_new.function.arguments,
                        "requires_confirmation": False,
                    })

                    result: ToolResult | None = None
                    async for _piece in _stream_tool_with_keepalive(tc_new):
                        if isinstance(_piece, ToolResult):
                            result = _piece
                        else:
                            yield _piece

                    assert result is not None
                    result_str = json.dumps(
                        result.data if result.success else {"error": result.error},
                        default=str,
                    )
                    yield _sse("tool_result", {
                        "tool_call_id": tc_new.id,
                        "name": tc_new.function.name,
                        "result": result_str,
                    })

                    input_items.append({
                        "type": "function_call_output",
                        "call_id": tc_new.id,
                        "output": result_str,
                    })

        yield _sse("done", {"session_id": body.session_id})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

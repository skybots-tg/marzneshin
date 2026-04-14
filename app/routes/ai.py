import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai import tools as _tools_import  # noqa: F401 — register all tools
from app.ai.models import (
    ChatMessage,
    ChatRequest,
    ConfirmRequest,
    ConfirmAction,
    MessageRole,
    ToolCall,
)
from app.ai.openai_client import (
    chat_completion,
    list_models,
    stream_chat_completion,
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
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {str(e)}")


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
    model = body.model or ai_settings.default_model
    session_id = body.session_id or create_session_id()

    async def event_stream():
        messages = list(body.messages)
        max_iterations = 10

        for iteration in range(max_iterations):
            accumulated_content = ""
            tool_calls_result = []
            has_tool_calls = False

            try:
                async for chunk in stream_chat_completion(
                    api_key=api_key,
                    messages=messages,
                    model=model,
                    max_tokens=ai_settings.max_tokens,
                    temperature=ai_settings.temperature,
                    custom_system_prompt=ai_settings.system_prompt,
                ):
                    if chunk["type"] == "content":
                        yield _sse("content", {"text": chunk["content"]})
                    elif chunk["type"] == "tool_calls":
                        tool_calls_result = chunk["tool_calls"]
                        has_tool_calls = True
                    elif chunk["type"] == "done":
                        accumulated_content = chunk.get("content", "")
            except Exception as e:
                logger.exception("OpenAI streaming error")
                yield _sse("error", {"message": f"OpenAI error: {str(e)}"})
                return

            if not has_tool_calls:
                yield _sse("done", {"session_id": session_id})
                return

            assistant_msg = ChatMessage(
                role=MessageRole.assistant,
                content=accumulated_content if accumulated_content else None,
                tool_calls=tool_calls_result,
            )
            messages.append(assistant_msg)

            all_read = True
            for tc in tool_calls_result:
                if requires_confirmation(tc):
                    all_read = False
                    yield _sse("tool_call", {
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                        "requires_confirmation": True,
                    })

                    store_pending(session_id, tc, messages, model)

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

                    with GetDB() as tool_db:
                        result = await execute_tool(tc, tool_db)

                    result_str = json.dumps(
                        result.data if result.success else {"error": result.error},
                        default=str,
                    )
                    yield _sse("tool_result", {
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "result": result_str,
                    })

                    messages.append(ChatMessage(
                        role=MessageRole.tool,
                        content=result_str,
                        tool_call_id=tc.id,
                    ))

            if not all_read:
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

    pending = get_pending(body.session_id)
    if not pending:
        raise HTTPException(status_code=404, detail="No pending confirmation found for this session")

    messages = list(pending.messages_snapshot)
    model = pending.model
    tc = pending.tool_call
    remove_pending(body.session_id)

    if body.action == ConfirmAction.reject:
        rejection = build_rejection_message(pending)
        messages.append(ChatMessage(
            role=MessageRole.tool,
            content=json.dumps({"rejected": True, "message": rejection}),
            tool_call_id=tc.id,
        ))
    else:
        with GetDB() as tool_db:
            result = await execute_tool(tc, tool_db)

        result_str = json.dumps(
            result.data if result.success else {"error": result.error},
            default=str,
        )
        messages.append(ChatMessage(
            role=MessageRole.tool,
            content=result_str,
            tool_call_id=tc.id,
        ))

    async def event_stream():
        nonlocal messages

        max_iterations = 10
        for iteration in range(max_iterations):
            accumulated_content = ""
            tool_calls_result = []
            has_tool_calls = False

            try:
                async for chunk in stream_chat_completion(
                    api_key=api_key,
                    messages=messages,
                    model=model,
                    max_tokens=ai_settings.max_tokens,
                    temperature=ai_settings.temperature,
                    custom_system_prompt=ai_settings.system_prompt,
                ):
                    if chunk["type"] == "content":
                        yield _sse("content", {"text": chunk["content"]})
                    elif chunk["type"] == "tool_calls":
                        tool_calls_result = chunk["tool_calls"]
                        has_tool_calls = True
                    elif chunk["type"] == "done":
                        accumulated_content = chunk.get("content", "")
            except Exception as e:
                logger.exception("OpenAI streaming error on confirm")
                yield _sse("error", {"message": f"OpenAI error: {str(e)}"})
                return

            if not has_tool_calls:
                yield _sse("done", {"session_id": body.session_id})
                return

            assistant_msg = ChatMessage(
                role=MessageRole.assistant,
                content=accumulated_content if accumulated_content else None,
                tool_calls=tool_calls_result,
            )
            messages.append(assistant_msg)

            for tc_new in tool_calls_result:
                if requires_confirmation(tc_new):
                    yield _sse("tool_call", {
                        "tool_call_id": tc_new.id,
                        "name": tc_new.function.name,
                        "arguments": tc_new.function.arguments,
                        "requires_confirmation": True,
                    })
                    store_pending(body.session_id, tc_new, messages, model)
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

                    with GetDB() as tool_db:
                        result = await execute_tool(tc_new, tool_db)

                    result_str = json.dumps(
                        result.data if result.success else {"error": result.error},
                        default=str,
                    )
                    yield _sse("tool_result", {
                        "tool_call_id": tc_new.id,
                        "name": tc_new.function.name,
                        "result": result_str,
                    })

                    messages.append(ChatMessage(
                        role=MessageRole.tool,
                        content=result_str,
                        tool_call_id=tc_new.id,
                    ))

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

import logging
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from app.ai.models import (
    AIModelInfo,
    ChatMessage,
    MessageRole,
    ToolCall,
    ToolCallFunction,
)
from app.ai.tool_registry import get_openai_tools_schema

logger = logging.getLogger(__name__)

REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")

_OUTPUT_ITEM_FIELDS = {
    "function_call": {"type", "id", "call_id", "name", "arguments", "status"},
    "message": {"type", "id", "role", "content", "status"},
    "reasoning": {"type", "id", "content", "summary", "status"},
}


def _serialize_output_item(item) -> dict[str, Any]:
    """Serialize a Responses API output item, keeping only API-accepted fields."""
    raw = item.model_dump(mode="json")
    allowed = _OUTPUT_ITEM_FIELDS.get(raw.get("type", ""))
    if allowed:
        return {k: v for k, v in raw.items() if k in allowed and v is not None}
    return raw


def is_reasoning_model(model: str) -> bool:
    lower = model.lower()
    return any(lower.startswith(p) for p in REASONING_MODEL_PREFIXES)


def build_instructions(custom_prompt: str = "") -> str:
    from app.ai.tool_registry import get_all_tools

    tools_desc = []
    for t in get_all_tools():
        conf = (
            " [REQUIRES CONFIRMATION]"
            if t.requires_confirmation
            else " [read-only]"
        )
        tools_desc.append(f"- {t.name}: {t.description}{conf}")

    tools_section = "\n".join(tools_desc)

    base = f"""You are an AI assistant for Marzneshin — a proxy management panel.
You help administrators manage nodes, diagnose issues, and configure the system.

Available tools:
{tools_section}

Guidelines:
- Before making changes (write operations), explain what you plan to do and why.
- Use read tools to gather information before suggesting changes.
- When diagnosing issues, check node health, logs, and configs systematically.
- Be concise but thorough in your analysis.
- If a tool returns an error, explain what went wrong and suggest alternatives.
- Respond in the same language the user writes in.
"""

    if custom_prompt:
        base += f"\nAdditional instructions from admin:\n{custom_prompt}\n"

    return base


def convert_messages_to_input(
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


async def stream_response(
    api_key: str,
    input_items: list[dict[str, Any]],
    instructions: str,
    model: str = "gpt-4o",
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
    temperature: float = 0.7,
) -> AsyncGenerator[dict, None]:
    """Stream a response using the Responses API.

    Yields dicts with 'type' key:
      - 'content': text delta
      - 'tool_calls': list of ToolCall objects
      - 'done': final event with content, output_items
    """
    client = AsyncOpenAI(api_key=api_key)

    params: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": input_items,
        "max_output_tokens": max_tokens,
    }

    if tools:
        params["tools"] = tools

    if is_reasoning_model(model):
        params["reasoning"] = {"effort": "medium"}
    else:
        params["temperature"] = temperature

    content_acc = ""
    tool_calls: list[ToolCall] = []
    output_items: list[dict[str, Any]] = []

    params["stream"] = True
    stream = await client.responses.create(**params)

    async for event in stream:
        etype = type(event).__name__

        if etype == "ResponseTextDeltaEvent":
            content_acc += event.delta
            yield {"type": "content", "content": event.delta}

        elif etype == "ResponseOutputItemDoneEvent":
            item = event.item
            output_items.append(_serialize_output_item(item))
            if item.type == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=item.call_id,
                        type="function",
                        function=ToolCallFunction(
                            name=item.name,
                            arguments=item.arguments,
                        ),
                    )
                )

    if tool_calls:
        yield {"type": "tool_calls", "tool_calls": tool_calls}

    yield {
        "type": "done",
        "content": content_acc,
        "output_items": output_items,
    }


async def list_models(api_key: str) -> list[AIModelInfo]:
    client = AsyncOpenAI(api_key=api_key)
    models_page = await client.models.list()

    result = []
    for m in models_page.data:
        mid = m.id.lower()
        is_text = any(
            mid.startswith(p)
            for p in ("gpt-", "o1", "o3", "o4", "chatgpt-")
        )
        if not is_text:
            continue

        skip_prefixes = (
            "gpt-image", "gpt-audio", "gpt-realtime",
            "chatgpt-image",
        )
        skip_suffixes = (
            "-transcribe", "-tts", "-audio-preview",
            "-realtime-preview", "-diarize",
        )
        if any(mid.startswith(p) for p in skip_prefixes):
            continue
        if any(mid.endswith(s) for s in skip_suffixes):
            continue

        result.append(AIModelInfo(
            id=m.id,
            owned_by=m.owned_by,
            reasoning=is_reasoning_model(m.id),
        ))

    result.sort(key=lambda x: x.id)
    return result

import json
import logging
from typing import AsyncGenerator

from openai import AsyncOpenAI

from app.ai.models import AIModelInfo, ChatMessage, MessageRole, ToolCall, ToolCallFunction
from app.ai.tool_registry import get_openai_tools_schema

logger = logging.getLogger(__name__)

THINKING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5-thinking", "gpt-5.2-thinking")


def is_thinking_model(model: str) -> bool:
    lower = model.lower()
    for prefix in THINKING_MODEL_PREFIXES:
        if lower.startswith(prefix):
            return True
    return False


def _build_params(
    model: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int = 16384,
    temperature: float = 0.7,
) -> dict:
    params = {
        "model": model,
        "messages": messages,
    }

    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
        params["parallel_tool_calls"] = True

    if is_thinking_model(model):
        params["max_completion_tokens"] = max_tokens
    else:
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature

    return params


def _build_system_prompt(custom_prompt: str = "") -> str:
    from app.ai.tool_registry import get_all_tools

    tools_desc = []
    for t in get_all_tools():
        conf = " [REQUIRES CONFIRMATION]" if t.requires_confirmation else " [read-only]"
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


def _messages_to_openai(
    messages: list[ChatMessage],
    system_prompt: str,
) -> list[dict]:
    result = [{"role": "system", "content": system_prompt}]

    for msg in messages:
        d = {"role": msg.role}
        if msg.content is not None:
            d["content"] = msg.content
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        if msg.name:
            d["name"] = msg.name
        result.append(d)

    return result


async def chat_completion(
    api_key: str,
    messages: list[ChatMessage],
    model: str = "gpt-4o",
    max_tokens: int = 16384,
    temperature: float = 0.7,
    custom_system_prompt: str = "",
) -> ChatMessage:
    client = AsyncOpenAI(api_key=api_key)
    system_prompt = _build_system_prompt(custom_system_prompt)
    openai_messages = _messages_to_openai(messages, system_prompt)
    tools = get_openai_tools_schema()

    params = _build_params(model, openai_messages, tools, max_tokens, temperature)

    response = await client.chat.completions.create(**params)
    choice = response.choices[0]
    msg = choice.message

    tool_calls = None
    if msg.tool_calls:
        tool_calls = [
            ToolCall(
                id=tc.id,
                type="function",
                function=ToolCallFunction(
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ),
            )
            for tc in msg.tool_calls
        ]

    return ChatMessage(
        role=MessageRole.assistant,
        content=msg.content,
        tool_calls=tool_calls,
    )


async def stream_chat_completion(
    api_key: str,
    messages: list[ChatMessage],
    model: str = "gpt-4o",
    max_tokens: int = 16384,
    temperature: float = 0.7,
    custom_system_prompt: str = "",
) -> AsyncGenerator[dict, None]:
    """Stream response. Yields dicts with 'type' key: 'content', 'tool_calls', 'done'."""
    client = AsyncOpenAI(api_key=api_key)
    system_prompt = _build_system_prompt(custom_system_prompt)
    openai_messages = _messages_to_openai(messages, system_prompt)
    tools = get_openai_tools_schema()

    params = _build_params(model, openai_messages, tools, max_tokens, temperature)
    params["stream"] = True

    tool_calls_acc: dict[int, dict] = {}
    content_acc = ""

    stream = await client.chat.completions.create(**params)

    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            continue

        if delta.content:
            content_acc += delta.content
            yield {"type": "content", "content": delta.content}

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {
                        "id": tc_delta.id or "",
                        "name": "",
                        "arguments": "",
                    }
                if tc_delta.id:
                    tool_calls_acc[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_calls_acc[idx]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

        if chunk.choices[0].finish_reason:
            break

    if tool_calls_acc:
        tool_calls = []
        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    type="function",
                    function=ToolCallFunction(
                        name=tc["name"],
                        arguments=tc["arguments"],
                    ),
                )
            )
        yield {"type": "tool_calls", "tool_calls": tool_calls}

    yield {"type": "done", "content": content_acc}


async def list_models(api_key: str) -> list[AIModelInfo]:
    client = AsyncOpenAI(api_key=api_key)
    models_page = await client.models.list()

    result = []
    for m in models_page.data:
        mid = m.id.lower()
        is_text_model = any(
            mid.startswith(p)
            for p in ("gpt-", "o1", "o3", "o4", "chatgpt-")
        )
        if is_text_model:
            result.append(AIModelInfo(id=m.id, owned_by=m.owned_by))

    result.sort(key=lambda x: x.id)
    return result

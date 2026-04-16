"""Builds the Marzneshin AI agent using the OpenAI Agents SDK.

One top-level agent owns the whole assistant conversation and has access
to every registered tool. Tools that mutate state are gated by SDK's
built-in approval flow (see `FunctionTool.needs_approval`), so dangerous
actions surface as run interruptions the caller can resolve.
"""
import logging

from agents import Agent, ModelSettings, set_tracing_disabled
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

from app.ai import tools as _tools_import  # noqa: F401 — register all tools
from app.ai.tool_registry import build_function_tools, get_all_tools

logger = logging.getLogger(__name__)

set_tracing_disabled(True)

REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def is_reasoning_model(model: str) -> bool:
    lower = model.lower()
    return any(lower.startswith(p) for p in REASONING_MODEL_PREFIXES)


def build_instructions(custom_prompt: str = "") -> str:
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
- After tool calls finish, always produce a final textual response that summarizes
  what you did and what the user should know. Never end a turn with only tool calls.
- Respond in the same language the user writes in.
"""

    if custom_prompt:
        base += f"\nAdditional instructions from admin:\n{custom_prompt}\n"

    return base


def build_agent(
    api_key: str,
    model_name: str,
    system_prompt: str = "",
    max_tokens: int = 16384,
    temperature: float = 0.7,
    reasoning_effort: str = "medium",
) -> Agent:
    """Construct an Agent bound to a specific OpenAI client and model."""
    client = AsyncOpenAI(api_key=api_key)
    model = OpenAIResponsesModel(model=model_name, openai_client=client)

    if is_reasoning_model(model_name):
        model_settings = ModelSettings(
            max_tokens=max_tokens,
            reasoning={"effort": reasoning_effort},
        )
    else:
        model_settings = ModelSettings(
            max_tokens=max_tokens,
            temperature=temperature,
        )

    return Agent(
        name="Marzneshin Assistant",
        instructions=build_instructions(system_prompt),
        model=model,
        model_settings=model_settings,
        tools=build_function_tools(),
    )

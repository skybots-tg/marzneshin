"""Thin wrapper around the OpenAI client for non-Agents tasks.

The main chat loop now lives in `app.ai.agent` + `agents.Runner`, but we
still need a way to list available models for the settings UI.
"""
import logging

from openai import AsyncOpenAI

from app.ai.agent import is_reasoning_model
from app.ai.models import AIModelInfo

logger = logging.getLogger(__name__)


async def list_models(api_key: str) -> list[AIModelInfo]:
    client = AsyncOpenAI(api_key=api_key)
    models_page = await client.models.list()

    result: list[AIModelInfo] = []
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

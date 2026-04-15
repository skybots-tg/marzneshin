import inspect
import logging
from typing import Any, Callable, Coroutine

from app.ai.models import ToolDefinition

logger = logging.getLogger(__name__)

_registry: dict[str, dict] = {}


def _python_type_to_json_schema(annotation) -> dict:
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        args = annotation.__args__
        return {
            "type": "array",
            "items": _python_type_to_json_schema(args[0]) if args else {"type": "string"},
        }
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is str:
        return {"type": "string"}
    if annotation is dict or origin is dict:
        return {"type": "object"}
    return {"type": "string"}


def register_tool(
    name: str,
    description: str,
    requires_confirmation: bool = False,
):
    def decorator(func: Callable[..., Coroutine]):
        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name == "db":
                continue
            annotation = param.annotation if param.annotation != inspect.Parameter.empty else str
            prop = _python_type_to_json_schema(annotation)
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
            else:
                prop["default"] = param.default
            properties[param_name] = prop

        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
            requires_confirmation=requires_confirmation,
        )

        _registry[name] = {
            "definition": tool_def,
            "handler": func,
        }
        logger.debug("Registered AI tool: %s (confirmation=%s)", name, requires_confirmation)
        return func

    return decorator


def get_tool(name: str) -> dict | None:
    return _registry.get(name)


def get_all_tools() -> list[ToolDefinition]:
    return [entry["definition"] for entry in _registry.values()]


def get_openai_tools_schema() -> list[dict[str, Any]]:
    """Return tool schemas in the Responses API format (flat, internally tagged)."""
    result = []
    for entry in _registry.values():
        td = entry["definition"]
        result.append({
            "type": "function",
            "name": td.name,
            "description": td.description,
            "parameters": td.parameters,
            "strict": False,
        })
    return result

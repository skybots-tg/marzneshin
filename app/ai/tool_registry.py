"""Registry for AI tools used by the Agents SDK.

Keeps the legacy `@register_tool` decorator as a thin metadata layer:
each tool handler (signature: `async def handler(db: Session, **kwargs)`)
is registered with its name, description, JSON schema, and
`requires_confirmation` flag. `build_function_tools()` turns those entries
into `FunctionTool` objects consumable by `agents.Agent`.

The handler itself stays provider-agnostic. Adaptation to the SDK
happens in `build_function_tools()`: a fresh DB session is opened per
invocation (since handlers often call `db.close()`), arguments are parsed
from the model's JSON input, and the result is serialized back to JSON.
"""
import inspect
import json
import logging
from typing import Any, Callable, Coroutine

from agents import FunctionTool, RunContextWrapper

from app.ai.models import ToolDefinition
from app.db import GetDB

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
    """Decorator that records a tool handler and its metadata."""

    def decorator(func: Callable[..., Coroutine]):
        sig = inspect.signature(func)
        properties: dict[str, dict] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "db":
                continue
            annotation = (
                param.annotation
                if param.annotation != inspect.Parameter.empty
                else str
            )
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
        logger.debug(
            "Registered AI tool: %s (confirmation=%s)",
            name,
            requires_confirmation,
        )
        return func

    return decorator


def get_tool(name: str) -> dict | None:
    return _registry.get(name)


def get_all_tools() -> list[ToolDefinition]:
    return [entry["definition"] for entry in _registry.values()]


def _make_invoke(handler: Callable[..., Coroutine]):
    """Build an `on_invoke_tool` coroutine for the SDK.

    Opens a fresh DB session per call so that tool handlers that call
    `db.close()` (common for tools that delegate to `node_registry`)
    don't poison a shared session.
    """

    async def _invoke(_ctx: RunContextWrapper[Any], input_json: str) -> str:
        try:
            args = json.loads(input_json) if input_json else {}
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid arguments JSON: {str(e)}"})

        try:
            with GetDB() as db:
                result = await handler(db=db, **args)
            return json.dumps(result, default=str)
        except Exception as e:
            logger.exception("Tool %s execution failed", handler.__name__)
            return json.dumps({"error": str(e)})

    return _invoke


def build_function_tools() -> list[FunctionTool]:
    """Build SDK FunctionTool instances for all registered handlers."""
    tools: list[FunctionTool] = []
    for entry in _registry.values():
        td: ToolDefinition = entry["definition"]
        handler = entry["handler"]
        tools.append(
            FunctionTool(
                name=td.name,
                description=td.description,
                params_json_schema=td.parameters,
                on_invoke_tool=_make_invoke(handler),
                strict_json_schema=False,
                needs_approval=td.requires_confirmation,
            )
        )
    return tools

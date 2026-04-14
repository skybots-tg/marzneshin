from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: ToolCallFunction


class ChatMessage(BaseModel):
    role: MessageRole
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str = "gpt-4o"
    session_id: str | None = None


class PendingConfirmation(BaseModel):
    session_id: str
    tool_call: ToolCall
    tool_name: str
    tool_args: dict[str, Any]
    description: str
    messages_snapshot: list[ChatMessage]
    model: str


class ConfirmAction(StrEnum):
    approve = "approve"
    reject = "reject"


class ConfirmRequest(BaseModel):
    session_id: str
    action: ConfirmAction


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    requires_confirmation: bool = False


class ToolResult(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None


class SSEEvent(BaseModel):
    event: str
    data: Any


class AIModelInfo(BaseModel):
    id: str
    owned_by: str = ""

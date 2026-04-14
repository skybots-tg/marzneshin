export type MessageRole = 'user' | 'assistant' | 'tool' | 'system'

export interface ToolCallFunction {
    name: string
    arguments: string
}

export interface ToolCall {
    id: string
    type: string
    function: ToolCallFunction
}

export interface ChatMessage {
    role: MessageRole
    content: string | null
    tool_calls?: ToolCall[]
    tool_call_id?: string
    name?: string
}

export interface AISettings {
    api_key: string
    default_model: string
    thinking_model: string
    max_tokens: number
    temperature: number
    system_prompt: string
}

export interface AISettingsResponse {
    configured: boolean
    default_model: string
    thinking_model: string
    max_tokens: number
    temperature: number
    system_prompt: string
}

export interface AIModelInfo {
    id: string
    owned_by: string
}

export interface ToolDefinition {
    name: string
    description: string
    parameters: Record<string, unknown>
    requires_confirmation: boolean
}

export interface PendingConfirmation {
    session_id: string
    tool_name: string
    tool_args: Record<string, unknown>
}

export interface SSEToolCall {
    tool_call_id: string
    name: string
    arguments: string
    requires_confirmation: boolean
}

export interface SSEToolResult {
    tool_call_id: string
    name: string
    result: string
}

export type UIMessage = {
    id: string
    role: MessageRole
    content: string | null
    toolCalls?: SSEToolCall[]
    toolResults?: SSEToolResult[]
    pending?: PendingConfirmation
    isStreaming?: boolean
}

import { useAuth } from '@marzneshin/modules/auth'
import type { ChatMessage } from '../types'

export interface StreamCallbacks {
    onContent: (text: string) => void
    onToolCall: (data: {
        tool_call_id: string
        name: string
        arguments: string
        requires_confirmation: boolean
    }) => void
    onToolResult: (data: {
        tool_call_id: string
        name: string
        result: string
    }) => void
    onPendingConfirmation: (data: {
        session_id: string
        tool_name: string
        tool_args: Record<string, unknown>
    }) => void
    onDone: (data: { session_id: string }) => void
    onError: (message: string) => void
}

export async function streamChat(
    messages: ChatMessage[],
    model: string,
    sessionId: string | null,
    callbacks: StreamCallbacks,
    signal?: AbortSignal,
): Promise<void> {
    const token = useAuth.getState().getAuthToken()
    const baseUrl = import.meta.env.VITE_BASE_API || '/api/'
    const url = `${baseUrl.replace(/\/$/, '')}/ai/chat`

    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
            messages,
            model,
            session_id: sessionId,
        }),
        signal,
    })

    if (!response.ok) {
        const text = await response.text()
        callbacks.onError(`HTTP ${response.status}: ${text}`)
        return
    }

    const reader = response.body?.getReader()
    if (!reader) {
        callbacks.onError('No response body')
        return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = ''
        for (const line of lines) {
            if (line.startsWith('event: ')) {
                currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ') && currentEvent) {
                try {
                    const data = JSON.parse(line.slice(6))
                    switch (currentEvent) {
                        case 'content':
                            callbacks.onContent(data.text)
                            break
                        case 'tool_call':
                            callbacks.onToolCall(data)
                            break
                        case 'tool_result':
                            callbacks.onToolResult(data)
                            break
                        case 'pending_confirmation':
                            callbacks.onPendingConfirmation(data)
                            break
                        case 'done':
                            callbacks.onDone(data)
                            break
                        case 'error':
                            callbacks.onError(data.message)
                            break
                    }
                } catch {
                    // skip malformed JSON
                }
                currentEvent = ''
            }
        }
    }
}

export async function confirmAction(
    sessionId: string,
    action: 'approve' | 'reject',
    callbacks: StreamCallbacks,
    signal?: AbortSignal,
): Promise<void> {
    const token = useAuth.getState().getAuthToken()
    const baseUrl = import.meta.env.VITE_BASE_API || '/api/'
    const url = `${baseUrl.replace(/\/$/, '')}/ai/chat/confirm`

    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
            session_id: sessionId,
            action,
        }),
        signal,
    })

    if (!response.ok) {
        const text = await response.text()
        callbacks.onError(`HTTP ${response.status}: ${text}`)
        return
    }

    const reader = response.body?.getReader()
    if (!reader) {
        callbacks.onError('No response body')
        return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = ''
        for (const line of lines) {
            if (line.startsWith('event: ')) {
                currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ') && currentEvent) {
                try {
                    const data = JSON.parse(line.slice(6))
                    switch (currentEvent) {
                        case 'content':
                            callbacks.onContent(data.text)
                            break
                        case 'tool_call':
                            callbacks.onToolCall(data)
                            break
                        case 'tool_result':
                            callbacks.onToolResult(data)
                            break
                        case 'pending_confirmation':
                            callbacks.onPendingConfirmation(data)
                            break
                        case 'done':
                            callbacks.onDone(data)
                            break
                        case 'error':
                            callbacks.onError(data.message)
                            break
                    }
                } catch {
                    // skip malformed JSON
                }
                currentEvent = ''
            }
        }
    }
}

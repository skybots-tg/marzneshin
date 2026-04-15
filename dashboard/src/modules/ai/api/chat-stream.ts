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

async function consumeSseStream(
    reader: ReadableStreamDefaultReader<Uint8Array>,
    callbacks: StreamCallbacks,
): Promise<void> {
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = ''
    let streamTerminated = false

    while (true) {
        let chunk: ReadableStreamReadResult<Uint8Array>
        try {
            chunk = await reader.read()
        } catch (err) {
            callbacks.onError(
                `Поток ответа прерван (${String(err)}). ` +
                    'Частая причина — обрыв соединения или таймаут прокси при долгом выполнении инструмента.',
            )
            return
        }
        const { done, value } = chunk
        if (done) break
        if (!value) continue

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

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
                            streamTerminated = true
                            callbacks.onPendingConfirmation(data)
                            break
                        case 'done':
                            streamTerminated = true
                            callbacks.onDone(data)
                            break
                        case 'error':
                            streamTerminated = true
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

    if (!streamTerminated) {
        callbacks.onError(
            'Поток ответа завершился неожиданно. ' +
                'Возможная причина — ошибка на сервере или таймаут прокси.',
        )
    }
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

    await consumeSseStream(reader, callbacks)
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

    await consumeSseStream(reader, callbacks)
}

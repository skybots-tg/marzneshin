import type { ChatMessage, UIMessage } from '../types'

const STORAGE_KEY = 'marzneshin-ai-chat-sessions'

export interface PersistedChatSession {
    id: string
    title: string
    updatedAt: number
    messages: UIMessage[]
    apiMessages: ChatMessage[]
    sessionId: string | null
    model: string
}

export function sanitizeMessagesForStorage(messages: UIMessage[]): UIMessage[] {
    return messages.map((m) => ({
        ...m,
        isStreaming: false,
        pending: undefined,
    }))
}

export function deriveChatTitle(messages: UIMessage[]): string {
    const firstUser = messages.find((m) => m.role === 'user' && m.content?.trim())
    if (!firstUser?.content) return ''
    const t = firstUser.content.trim().replace(/\s+/g, ' ')
    return t.length > 48 ? `${t.slice(0, 45)}…` : t
}

export function loadChatSessions(): PersistedChatSession[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) return []
        const parsed = JSON.parse(raw) as unknown
        if (!Array.isArray(parsed)) return []
        return parsed.filter(
            (s): s is PersistedChatSession =>
                typeof s === 'object' &&
                s !== null &&
                typeof (s as PersistedChatSession).id === 'string' &&
                Array.isArray((s as PersistedChatSession).messages),
        )
    } catch {
        return []
    }
}

export function saveChatSessions(sessions: PersistedChatSession[]): void {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
    } catch {
        // quota or private mode
    }
}

export function createEmptySession(): PersistedChatSession {
    return {
        id: crypto.randomUUID(),
        title: '',
        updatedAt: Date.now(),
        messages: [],
        apiMessages: [],
        sessionId: null,
        model: '',
    }
}

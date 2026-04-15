import { FC, useCallback, useEffect, useState } from 'react'
import { ChatInterface } from './chat-interface'
import { ChatSessionsSidebar } from './chat-sessions-sidebar'
import {
    createEmptySession,
    deriveChatTitle,
    loadChatSessions,
    saveChatSessions,
    sanitizeMessagesForStorage,
    type PersistedChatSession,
} from '../utils/chat-sessions-storage'
import type { ChatPersistenceSnapshot } from '../types'

interface ChatWorkspaceProps {
    onOpenSettings: () => void
}

export const ChatWorkspace: FC<ChatWorkspaceProps> = ({ onOpenSettings }) => {
    const [sessions, setSessions] = useState<PersistedChatSession[]>(() => {
        const loaded = loadChatSessions()
        if (loaded.length) return loaded
        const s = createEmptySession()
        saveChatSessions([s])
        return [s]
    })
    const [activeId, setActiveId] = useState(
        () => [...sessions].sort((a, b) => b.updatedAt - a.updatedAt)[0]!.id,
    )

    useEffect(() => {
        if (sessions.length && !sessions.some((s) => s.id === activeId)) {
            setActiveId(sessions[0]!.id)
        }
    }, [sessions, activeId])

    const activeSession = sessions.find((s) => s.id === activeId) ?? sessions[0]!

    const handlePersist = useCallback((chatId: string, snapshot: ChatPersistenceSnapshot) => {
        setSessions((prev) => {
            const idx = prev.findIndex((s) => s.id === chatId)
            if (idx === -1) return prev
            const prevS = prev[idx]
            const derivedTitle = deriveChatTitle(snapshot.messages)
            const next = [...prev]
            next[idx] = {
                ...prevS,
                messages: sanitizeMessagesForStorage(snapshot.messages),
                apiMessages: snapshot.apiMessages,
                sessionId: snapshot.sessionId,
                model: snapshot.model,
                title:
                    snapshot.messages.length === 0 ? '' : derivedTitle || prevS.title,
                updatedAt: Date.now(),
            }
            saveChatSessions(next)
            return next
        })
    }, [])

    const handleNew = useCallback(() => {
        const s = createEmptySession()
        setSessions((prev) => {
            const next = [s, ...prev]
            saveChatSessions(next)
            return next
        })
        setActiveId(s.id)
    }, [])

    const handleDelete = useCallback((id: string) => {
        setSessions((prev) => {
            let next = prev.filter((s) => s.id !== id)
            if (next.length === 0) {
                next = [createEmptySession()]
            }
            saveChatSessions(next)
            return next
        })
    }, [])

    const initialSnapshot: ChatPersistenceSnapshot = {
        messages: activeSession.messages,
        apiMessages: activeSession.apiMessages,
        sessionId: activeSession.sessionId,
        model: activeSession.model,
    }

    return (
        <div className="flex h-full min-h-0 gap-0">
            <ChatSessionsSidebar
                sessions={sessions}
                activeId={activeId}
                onSelect={setActiveId}
                onNew={handleNew}
                onDelete={handleDelete}
            />
            <div className="flex-1 min-w-0 min-h-0 flex flex-col">
                <ChatInterface
                    key={activeId}
                    persistChatId={activeId}
                    initialSnapshot={initialSnapshot}
                    onPersist={handlePersist}
                    onOpenSettings={onOpenSettings}
                />
            </div>
        </div>
    )
}

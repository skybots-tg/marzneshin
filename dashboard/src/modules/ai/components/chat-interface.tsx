import { FC, useCallback, useRef, useState, useEffect, KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Loader2, Settings2, Trash2 } from 'lucide-react'
import { Button } from '@marzneshin/common/components/ui'
import { Textarea } from '@marzneshin/common/components/ui'
import { useAISettingsQuery } from '../api'
import { streamChat, confirmAction } from '../api/chat-stream'
import { ModelSelector } from './model-selector'
import { MessageBubble } from './message-bubble'
import { ConfirmationDialog } from './confirmation-dialog'
import type {
    ChatMessage,
    UIMessage,
    PendingConfirmation,
    SSEToolCall,
    SSEToolResult,
} from '../types'

interface ChatInterfaceProps {
    onOpenSettings: () => void
}

export const ChatInterface: FC<ChatInterfaceProps> = ({ onOpenSettings }) => {
    const { t } = useTranslation()
    const { data: settings } = useAISettingsQuery()
    const configured = settings?.configured ?? false

    const [messages, setMessages] = useState<UIMessage[]>([])
    const [apiMessages, setApiMessages] = useState<ChatMessage[]>([])
    const [input, setInput] = useState('')
    const [model, setModel] = useState('')
    const [sessionId, setSessionId] = useState<string | null>(null)
    const [isStreaming, setIsStreaming] = useState(false)
    const [pending, setPending] = useState<PendingConfirmation | null>(null)
    const [confirmLoading, setConfirmLoading] = useState(false)

    const messagesEndRef = useRef<HTMLDivElement>(null)
    const abortRef = useRef<AbortController | null>(null)
    const assistantIdRef = useRef(0)

    useEffect(() => {
        if (settings?.default_model && !model) {
            setModel(settings.default_model)
        }
    }, [settings, model])

    const scrollToBottom = useCallback(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [])

    useEffect(scrollToBottom, [messages, scrollToBottom])

    const makeCallbacks = (assistantMsgId: string) => ({
        onContent: (text: string) => {
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantMsgId
                        ? { ...m, content: (m.content || '') + text, isStreaming: true }
                        : m
                )
            )
        },
        onToolCall: (data: SSEToolCall) => {
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantMsgId
                        ? {
                              ...m,
                              toolCalls: [...(m.toolCalls || []), data],
                          }
                        : m
                )
            )
        },
        onToolResult: (data: SSEToolResult) => {
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantMsgId
                        ? {
                              ...m,
                              toolResults: [...(m.toolResults || []), data],
                          }
                        : m
                )
            )
        },
        onPendingConfirmation: (data: PendingConfirmation) => {
            setPending(data)
            setSessionId(data.session_id)
        },
        onDone: (data: { session_id: string }) => {
            setSessionId(data.session_id)
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantMsgId ? { ...m, isStreaming: false } : m
                )
            )
            setIsStreaming(false)
        },
        onError: (message: string) => {
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantMsgId
                        ? {
                              ...m,
                              content: (m.content || '') + `\n\n❌ ${message}`,
                              isStreaming: false,
                          }
                        : m
                )
            )
            setIsStreaming(false)
        },
    })

    const handleSend = useCallback(async () => {
        const trimmed = input.trim()
        if (!trimmed || isStreaming || !configured) return

        const userMsg: UIMessage = {
            id: `user-${Date.now()}`,
            role: 'user',
            content: trimmed,
        }
        const apiUserMsg: ChatMessage = { role: 'user', content: trimmed }

        const newApiMessages = [...apiMessages, apiUserMsg]
        setApiMessages(newApiMessages)

        const assistantId = `assistant-${++assistantIdRef.current}`
        const assistantMsg: UIMessage = {
            id: assistantId,
            role: 'assistant',
            content: null,
            isStreaming: true,
        }

        setMessages((prev) => [...prev, userMsg, assistantMsg])
        setInput('')
        setIsStreaming(true)

        abortRef.current = new AbortController()
        const callbacks = makeCallbacks(assistantId)

        try {
            await streamChat(
                newApiMessages,
                model,
                sessionId,
                callbacks,
                abortRef.current.signal,
            )
        } catch (e: unknown) {
            if (e instanceof DOMException && e.name === 'AbortError') return
            callbacks.onError(String(e))
        }
    }, [input, isStreaming, configured, apiMessages, model, sessionId])

    const handleConfirm = useCallback(
        async (action: 'approve' | 'reject') => {
            if (!sessionId || !pending) return
            setConfirmLoading(true)
            setPending(null)

            const assistantId = `assistant-${++assistantIdRef.current}`
            const assistantMsg: UIMessage = {
                id: assistantId,
                role: 'assistant',
                content: null,
                isStreaming: true,
            }
            setMessages((prev) => [...prev, assistantMsg])
            setIsStreaming(true)

            const callbacks = makeCallbacks(assistantId)

            try {
                await confirmAction(sessionId, action, callbacks)
            } catch (e: unknown) {
                callbacks.onError(String(e))
            } finally {
                setConfirmLoading(false)
            }
        },
        [sessionId, pending],
    )

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSend()
        }
    }

    const handleClear = () => {
        setMessages([])
        setApiMessages([])
        setSessionId(null)
        setPending(null)
    }

    return (
        <div className="flex flex-col h-full">
            <div className="flex items-center gap-2 pb-3 border-b border-border/50">
                <ModelSelector
                    value={model}
                    onChange={setModel}
                    configured={configured}
                />
                <div className="flex-1" />
                <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    onClick={handleClear}
                    disabled={isStreaming || messages.length === 0}
                >
                    <Trash2 className="size-4" />
                </Button>
                <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    onClick={onOpenSettings}
                >
                    <Settings2 className="size-4" />
                </Button>
            </div>

            <div className="flex-1 overflow-y-auto py-4 space-y-4 min-h-0">
                {!configured && (
                    <div className="text-center text-muted-foreground text-sm py-8">
                        {t('ai.not-configured')}
                    </div>
                )}

                {configured && messages.length === 0 && (
                    <div className="text-center text-muted-foreground text-sm py-8">
                        {t('ai.placeholder')}
                    </div>
                )}

                {messages.map((msg) => (
                    <MessageBubble key={msg.id} message={msg} />
                ))}
                <div ref={messagesEndRef} />
            </div>

            <div className="pt-3 border-t border-border/50">
                <div className="flex items-end gap-2">
                    <Textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={t('ai.placeholder')}
                        className="min-h-[40px] max-h-[120px] resize-none text-sm"
                        disabled={!configured || isStreaming}
                        rows={1}
                    />
                    <Button
                        onClick={handleSend}
                        disabled={!input.trim() || isStreaming || !configured}
                        size="icon"
                        className="shrink-0 size-10"
                    >
                        {isStreaming ? (
                            <Loader2 className="size-4 animate-spin" />
                        ) : (
                            <Send className="size-4" />
                        )}
                    </Button>
                </div>
            </div>

            <ConfirmationDialog
                pending={pending}
                onApprove={() => handleConfirm('approve')}
                onReject={() => handleConfirm('reject')}
                loading={confirmLoading}
            />
        </div>
    )
}

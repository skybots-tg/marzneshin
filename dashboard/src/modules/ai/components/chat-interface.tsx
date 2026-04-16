import { FC, useCallback, useEffect, useRef, useState, KeyboardEvent, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Loader2, Settings2, Trash2, ShieldCheck, X } from 'lucide-react'
import { useDebouncedCallback } from 'use-debounce'
import { Button } from '@marzneshin/common/components/ui'
import { Textarea } from '@marzneshin/common/components/ui'
import { useAISettingsQuery } from '../api'
import { streamChat, confirmAction } from '../api/chat-stream'
import { ModelSelector } from './model-selector'
import { MessageBubble } from './message-bubble'
import { ConfirmationDialog } from './confirmation-dialog'
import type {
    ChatMessage,
    ChatPersistenceSnapshot,
    UIMessage,
    PendingConfirmation,
    SSEToolCall,
    SSEToolResult,
} from '../types'

function maxAssistantCounter(messages: UIMessage[]): number {
    let max = 0
    for (const m of messages) {
        const match = /^assistant-(\d+)$/.exec(m.id)
        if (match) max = Math.max(max, Number(match[1]))
    }
    return max
}

interface ChatInterfaceProps {
    persistChatId: string
    initialSnapshot: ChatPersistenceSnapshot
    onPersist: (chatId: string, snapshot: ChatPersistenceSnapshot) => void
    onOpenSettings: () => void
}

export const ChatInterface: FC<ChatInterfaceProps> = ({
    persistChatId,
    initialSnapshot,
    onPersist,
    onOpenSettings,
}) => {
    const { t } = useTranslation()
    const { data: settings } = useAISettingsQuery()
    const configured = settings?.configured ?? false

    const [messages, setMessages] = useState<UIMessage[]>(() => initialSnapshot.messages)
    const [apiMessages, setApiMessages] = useState<ChatMessage[]>(() => initialSnapshot.apiMessages)
    const [input, setInput] = useState('')
    const [model, setModel] = useState(() => initialSnapshot.model)
    const [sessionId, setSessionId] = useState<string | null>(() => initialSnapshot.sessionId)
    const [isStreaming, setIsStreaming] = useState(false)
    const [pending, setPending] = useState<PendingConfirmation | null>(null)
    const [confirmLoading, setConfirmLoading] = useState(false)
    const [autoApprove, setAutoApprove] = useState(false)

    const messagesEndRef = useRef<HTMLDivElement>(null)
    const abortRef = useRef<AbortController | null>(null)
    const assistantIdRef = useRef(maxAssistantCounter(initialSnapshot.messages))
    const autoApproveRef = useRef(false)
    const currentTurnRef = useRef<{
        content: string
        toolCalls: SSEToolCall[]
        toolResults: SSEToolResult[]
    }>({ content: '', toolCalls: [], toolResults: [] })

    const finalizeTurn = useCallback(() => {
        const turn = currentTurnRef.current
        const toAppend: ChatMessage[] = []
        if (turn.content || turn.toolCalls.length > 0) {
            const assistantMsg: ChatMessage = {
                role: 'assistant',
                content: turn.content || null,
            }
            if (turn.toolCalls.length > 0) {
                assistantMsg.tool_calls = turn.toolCalls.map((tc) => ({
                    id: tc.tool_call_id,
                    type: 'function',
                    function: { name: tc.name, arguments: tc.arguments },
                }))
            }
            toAppend.push(assistantMsg)
        }
        for (const tr of turn.toolResults) {
            toAppend.push({
                role: 'tool',
                content: tr.result,
                tool_call_id: tr.tool_call_id,
                name: tr.name,
            })
        }
        if (toAppend.length > 0) {
            setApiMessages((prev) => [...prev, ...toAppend])
        }
        currentTurnRef.current = {
            content: '',
            toolCalls: [],
            toolResults: [],
        }
    }, [])

    const debouncedPersist = useDebouncedCallback(
        (snap: ChatPersistenceSnapshot, chatId: string) => onPersist(chatId, snap),
        400,
    )

    useEffect(() => {
        debouncedPersist(
            {
                messages,
                apiMessages,
                sessionId,
                model,
            },
            persistChatId,
        )
    }, [messages, apiMessages, sessionId, model, persistChatId, debouncedPersist])

    useEffect(() => {
        return () => {
            debouncedPersist.flush()
        }
    }, [debouncedPersist])

    useEffect(() => {
        if (settings?.default_model && !model) {
            setModel(settings.default_model)
        }
    }, [settings, model])

    const scrollToBottom = useCallback(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [])

    useEffect(scrollToBottom, [messages, scrollToBottom])

    const makeCallbacks = useMemo(
        () => (assistantMsgId: string) => ({
            onContent: (text: string) => {
                currentTurnRef.current.content += text
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantMsgId
                            ? { ...m, content: (m.content || '') + text, isStreaming: true }
                            : m,
                    ),
                )
            },
            onToolCall: (data: SSEToolCall) => {
                currentTurnRef.current.toolCalls.push(data)
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantMsgId
                            ? {
                                  ...m,
                                  toolCalls: [...(m.toolCalls || []), data],
                              }
                            : m,
                    ),
                )
            },
            onToolResult: (data: SSEToolResult) => {
                currentTurnRef.current.toolResults.push(data)
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantMsgId
                            ? {
                                  ...m,
                                  toolResults: [...(m.toolResults || []), data],
                              }
                            : m,
                    ),
                )
            },
            onPendingConfirmation: (data: PendingConfirmation) => {
                setSessionId(data.session_id)
                finalizeTurn()
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantMsgId ? { ...m, isStreaming: false } : m,
                    ),
                )
                setIsStreaming(false)
                // In auto-approve mode we skip the dialog and let the
                // useEffect below trigger the continuation.
                setPending(data)
            },
            onDone: (data: { session_id: string }) => {
                setSessionId(data.session_id)
                finalizeTurn()
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantMsgId ? { ...m, isStreaming: false } : m,
                    ),
                )
                setIsStreaming(false)
            },
            onError: (message: string) => {
                finalizeTurn()
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantMsgId
                            ? {
                                  ...m,
                                  content: (m.content || '') + `\n\n❌ ${message}`,
                                  isStreaming: false,
                              }
                            : m,
                    ),
                )
                setIsStreaming(false)
            },
        }),
        [finalizeTurn],
    )

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

        currentTurnRef.current = { content: '', toolCalls: [], toolResults: [] }
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
            if (e instanceof DOMException && e.name === 'AbortError') {
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantId ? { ...m, isStreaming: false } : m,
                    ),
                )
                setIsStreaming(false)
                return
            }
            callbacks.onError(String(e))
        } finally {
            setIsStreaming(false)
            setMessages((prev) =>
                prev.map((m) =>
                    m.id === assistantId ? { ...m, isStreaming: false } : m,
                ),
            )
        }
    }, [input, isStreaming, configured, apiMessages, model, sessionId, makeCallbacks])

    const handleConfirm = useCallback(
        async (action: 'approve' | 'reject') => {
            if (!sessionId) return
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

            currentTurnRef.current = { content: '', toolCalls: [], toolResults: [] }
            const callbacks = makeCallbacks(assistantId)

            try {
                await confirmAction(sessionId, action, callbacks)
            } catch (e: unknown) {
                callbacks.onError(String(e))
            } finally {
                setConfirmLoading(false)
                setIsStreaming(false)
                setMessages((prev) =>
                    prev.map((m) =>
                        m.id === assistantId ? { ...m, isStreaming: false } : m,
                    ),
                )
            }
        },
        [sessionId, makeCallbacks],
    )

    useEffect(() => {
        if (pending && autoApproveRef.current) {
            handleConfirm('approve')
        }
    }, [pending, handleConfirm])

    const handleApproveAll = useCallback(() => {
        autoApproveRef.current = true
        setAutoApprove(true)
        handleConfirm('approve')
    }, [handleConfirm])

    const disableAutoApprove = useCallback(() => {
        autoApproveRef.current = false
        setAutoApprove(false)
    }, [])

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
        autoApproveRef.current = false
        setAutoApprove(false)
        assistantIdRef.current = 0
        currentTurnRef.current = { content: '', toolCalls: [], toolResults: [] }
    }

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex items-center gap-2 pb-3 border-b border-border/50">
                <ModelSelector
                    value={model}
                    onChange={setModel}
                    configured={configured}
                />
                {autoApprove && (
                    <button
                        type="button"
                        onClick={disableAutoApprove}
                        className="inline-flex items-center gap-1.5 px-2 h-7 rounded-md bg-amber-500/15 border border-amber-500/40 text-amber-700 dark:text-amber-400 text-xs font-medium hover:bg-amber-500/25 transition-colors"
                        title={t('ai.auto-approve-disable')}
                    >
                        <ShieldCheck className="size-3.5" />
                        {t('ai.auto-approve-on')}
                        <X className="size-3" />
                    </button>
                )}
                <div className="flex-1" />
                <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    onClick={handleClear}
                    disabled={isStreaming || messages.length === 0}
                    title={t('ai.clear-chat')}
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
                pending={autoApprove ? null : pending}
                onApprove={() => handleConfirm('approve')}
                onApproveAll={handleApproveAll}
                onReject={() => handleConfirm('reject')}
                loading={confirmLoading}
            />
        </div>
    )
}

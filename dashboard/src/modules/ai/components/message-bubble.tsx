import { FC } from 'react'
import { Bot, User } from 'lucide-react'
import { cn } from '@marzneshin/common/utils'
import { ToolCallDisplay } from './tool-call-display'
import type { UIMessage } from '../types'

interface MessageBubbleProps {
    message: UIMessage
}

export const MessageBubble: FC<MessageBubbleProps> = ({ message }) => {
    const isUser = message.role === 'user'
    const isAssistant = message.role === 'assistant'

    if (message.role === 'tool') return null

    return (
        <div
            className={cn(
                'flex gap-3 w-full',
                isUser ? 'justify-end' : 'justify-start'
            )}
        >
            {isAssistant && (
                <div className="shrink-0 size-7 rounded-full bg-primary/10 flex items-center justify-center mt-1">
                    <Bot className="size-4 text-primary" />
                </div>
            )}

            <div
                className={cn(
                    'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
                    isUser
                        ? 'bg-primary text-primary-foreground rounded-br-md'
                        : 'bg-muted rounded-bl-md'
                )}
            >
                {message.toolCalls?.map((tc) => (
                    <ToolCallDisplay
                        key={tc.tool_call_id}
                        toolCall={tc}
                        result={message.toolResults?.find(
                            (r) => r.tool_call_id === tc.tool_call_id
                        )}
                    />
                ))}

                {message.content && (
                    <div className="whitespace-pre-wrap break-words">
                        {message.content}
                    </div>
                )}

                {message.isStreaming && !message.content && !message.toolCalls?.length && (
                    <div className="flex items-center gap-1.5">
                        <div className="size-1.5 rounded-full bg-current animate-pulse" />
                        <div className="size-1.5 rounded-full bg-current animate-pulse [animation-delay:200ms]" />
                        <div className="size-1.5 rounded-full bg-current animate-pulse [animation-delay:400ms]" />
                    </div>
                )}
            </div>

            {isUser && (
                <div className="shrink-0 size-7 rounded-full bg-primary flex items-center justify-center mt-1">
                    <User className="size-4 text-primary-foreground" />
                </div>
            )}
        </div>
    )
}

import { FC, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Wrench, CheckCircle2 } from 'lucide-react'
import type { SSEToolCall, SSEToolResult } from '../types'

interface ToolCallDisplayProps {
    toolCall: SSEToolCall
    result?: SSEToolResult
}

export const ToolCallDisplay: FC<ToolCallDisplayProps> = ({ toolCall, result }) => {
    const { t } = useTranslation()
    const [expanded, setExpanded] = useState(false)

    let parsedArgs: string
    try {
        parsedArgs = JSON.stringify(JSON.parse(toolCall.arguments), null, 2)
    } catch {
        parsedArgs = toolCall.arguments
    }

    let parsedResult: string | null = null
    if (result) {
        try {
            parsedResult = JSON.stringify(JSON.parse(result.result), null, 2)
        } catch {
            parsedResult = result.result
        }
    }

    return (
        <div className="my-1 rounded-md border border-border/50 bg-muted/30 text-xs">
            <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-muted/50 transition-colors"
            >
                {expanded ? (
                    <ChevronDown className="size-3.5 shrink-0" />
                ) : (
                    <ChevronRight className="size-3.5 shrink-0" />
                )}
                <Wrench className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="font-medium">{toolCall.name}</span>
                {result && (
                    <CheckCircle2 className="size-3.5 shrink-0 text-green-500 ml-auto" />
                )}
                {toolCall.requires_confirmation && !result && (
                    <span className="ml-auto text-amber-500 font-medium">
                        {t('ai.confirm-title')}
                    </span>
                )}
            </button>

            {expanded && (
                <div className="px-3 pb-2 space-y-2">
                    <div>
                        <div className="text-muted-foreground mb-1 text-[11px] uppercase tracking-wider">
                            Arguments
                        </div>
                        <pre className="bg-background rounded p-2 overflow-x-auto max-h-48 text-[11px] leading-relaxed">
                            {parsedArgs}
                        </pre>
                    </div>
                    {parsedResult && (
                        <div>
                            <div className="text-muted-foreground mb-1 text-[11px] uppercase tracking-wider">
                                {t('ai.tool-result')}
                            </div>
                            <pre className="bg-background rounded p-2 overflow-x-auto max-h-64 text-[11px] leading-relaxed">
                                {parsedResult}
                            </pre>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

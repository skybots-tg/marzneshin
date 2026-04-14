import { useQuery } from '@tanstack/react-query'
import { fetch } from '@marzneshin/common/utils/fetch'
import type { ToolDefinition } from '../types'

const AI_TOOLS_KEY = ['ai', 'tools']

export const useAIToolsQuery = () => {
    return useQuery<{ tools: ToolDefinition[]; total: number }>({
        queryKey: AI_TOOLS_KEY,
        queryFn: () => fetch('/ai/tools'),
        staleTime: 10 * 60 * 1000,
    })
}

import { useQuery } from '@tanstack/react-query'
import { fetch } from '@marzneshin/common/utils/fetch'
import type { AIModelInfo } from '../types'

const AI_MODELS_KEY = ['ai', 'models']

export const useAIModelsQuery = (enabled: boolean = true) => {
    return useQuery<{ models: AIModelInfo[] }>({
        queryKey: AI_MODELS_KEY,
        queryFn: () => fetch('/ai/models'),
        enabled,
        staleTime: 5 * 60 * 1000,
    })
}

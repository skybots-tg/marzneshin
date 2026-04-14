import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetch } from '@marzneshin/common/utils/fetch'
import type { AISettings, AISettingsResponse } from '../types'

const AI_SETTINGS_KEY = ['ai', 'settings']

export const useAISettingsQuery = () => {
    return useQuery<AISettingsResponse>({
        queryKey: AI_SETTINGS_KEY,
        queryFn: () => fetch('/ai/settings'),
    })
}

export const useAISettingsUpdateMutation = () => {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: (settings: AISettings) =>
            fetch<AISettingsResponse>('/ai/settings', {
                method: 'PUT',
                body: settings,
            }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: AI_SETTINGS_KEY })
        },
    })
}

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetch } from '@marzneshin/common/utils/fetch'
import type {
    AISkillCreate,
    AISkillDetail,
    AISkillSummary,
    AISkillUpdate,
} from '../types'

const AI_SKILLS_KEY = ['ai', 'skills'] as const

export const useAISkillsQuery = () =>
    useQuery<AISkillSummary[]>({
        queryKey: AI_SKILLS_KEY,
        queryFn: () => fetch('/ai/skills'),
    })

export const useAISkillQuery = (name: string | null) =>
    useQuery<AISkillDetail>({
        queryKey: [...AI_SKILLS_KEY, name],
        queryFn: () => fetch(`/ai/skills/${encodeURIComponent(name as string)}`),
        enabled: !!name,
    })

export const useAISkillCreateMutation = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (body: AISkillCreate) =>
            fetch<AISkillDetail>('/ai/skills', { method: 'POST', body }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: AI_SKILLS_KEY })
        },
    })
}

export const useAISkillUpdateMutation = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({
            name,
            body,
        }: {
            name: string
            body: AISkillUpdate
        }) =>
            fetch<AISkillDetail>(`/ai/skills/${encodeURIComponent(name)}`, {
                method: 'PUT',
                body,
            }),
        onSuccess: (_data, vars) => {
            qc.invalidateQueries({ queryKey: AI_SKILLS_KEY })
            qc.invalidateQueries({ queryKey: [...AI_SKILLS_KEY, vars.name] })
        },
    })
}

export const useAISkillRevertMutation = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (name: string) =>
            fetch<AISkillDetail>(
                `/ai/skills/${encodeURIComponent(name)}/revert`,
                { method: 'POST' }
            ),
        onSuccess: (_data, name) => {
            qc.invalidateQueries({ queryKey: AI_SKILLS_KEY })
            qc.invalidateQueries({ queryKey: [...AI_SKILLS_KEY, name] })
        },
    })
}

export const useAISkillDeleteMutation = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (name: string) =>
            fetch(`/ai/skills/${encodeURIComponent(name)}`, {
                method: 'DELETE',
            }),
        onSuccess: (_data, name) => {
            qc.invalidateQueries({ queryKey: AI_SKILLS_KEY })
            qc.invalidateQueries({ queryKey: [...AI_SKILLS_KEY, name] })
        },
    })
}

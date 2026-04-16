import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetch } from '@marzneshin/common/utils/fetch'

export interface SSHStatus {
    pin_configured: boolean
    credentials_saved: boolean
    session_unlocked: boolean
    unlock_ttl_seconds: number
    node_id?: number | null
    node_address?: string | null
    ssh_user?: string | null
    ssh_port?: number | null
}

export interface SSHUnlockBody {
    session_id: string
    pin: string
}

export interface SSHCredentialsBody {
    session_id: string
    node_id: number
    pin: string
    ssh_user: string
    ssh_port: number
    ssh_password?: string
    ssh_key?: string
}

export const fetchSSHStatus = (
    sessionId: string,
    nodeId?: number,
): Promise<SSHStatus> => {
    const params = new URLSearchParams({ session_id: sessionId })
    if (typeof nodeId === 'number') {
        params.set('node_id', String(nodeId))
    }
    return fetch<SSHStatus>(`/ai/ssh/status?${params.toString()}`)
}

export const useSSHUnlockMutation = () => {
    return useMutation({
        mutationFn: (body: SSHUnlockBody) =>
            fetch<SSHStatus>('/ai/ssh/unlock', {
                method: 'POST',
                body,
            }),
    })
}

export const useSSHSaveCredentialsMutation = () => {
    return useMutation({
        mutationFn: (body: SSHCredentialsBody) =>
            fetch<SSHStatus>('/ai/ssh/credentials', {
                method: 'POST',
                body,
            }),
    })
}

export const useSSHLockMutation = () => {
    return useMutation({
        mutationFn: (sessionId: string) =>
            fetch<{ locked: boolean; removed: boolean }>('/ai/ssh/lock', {
                method: 'POST',
                body: { session_id: sessionId },
            }),
    })
}

export const sshStatusQueryKey = (sessionId: string | null) =>
    ['ai-ssh-status', sessionId] as const

export const useSSHStatusQuery = (sessionId: string | null) =>
    useQuery({
        queryKey: sshStatusQueryKey(sessionId),
        queryFn: () => fetchSSHStatus(sessionId as string),
        enabled: !!sessionId,
        refetchInterval: 30_000,
        staleTime: 15_000,
        retry: 1,
    })

export const useInvalidateSSHStatus = () => {
    const qc = useQueryClient()
    return (sessionId: string | null) =>
        qc.invalidateQueries({ queryKey: sshStatusQueryKey(sessionId) })
}

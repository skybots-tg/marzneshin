import { useMutation, useQuery } from '@tanstack/react-query'
import { fetch } from '@marzneshin/common/utils/fetch'
import { useAuth } from '@marzneshin/modules/auth'

export type BackupMode = 'full' | 'light' | 'config'

export interface BackupInfo {
    modes: BackupMode[]
    heavy_history_tables: string[]
    default_history_days: number
}

export interface BackupJob {
    id: string
    mode: BackupMode
    history_days: number | null
    skip_tables: string[]
    status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
    phase: string
    table: string | null
    current_table_index: number
    total_tables: number
    rows_written_table: number
    expected_rows_table: number
    percent: number
    bytes_written: number
    dialect: string | null
    strategy: string | null
    error: string | null
    path: string | null
    started_at: number
    updated_at: number
    finished_at: number | null
    cancel_requested: boolean
}

export interface BackupArtefact {
    filename: string
    path: string
    size_bytes: number
    mtime: string
}

export interface CreateBackupBody {
    mode: BackupMode
    history_days?: number | null
    skip_tables?: string[]
}

export const fetchBackupInfo = (): Promise<BackupInfo> =>
    fetch<BackupInfo>('/ai/backup/info')

export const fetchBackupJob = (jobId: string): Promise<BackupJob> =>
    fetch<BackupJob>(`/ai/backup/jobs/${jobId}`)

export const fetchBackupJobs = (): Promise<{
    jobs: BackupJob[]
    artefacts: BackupArtefact[]
}> => fetch('/ai/backup/jobs')

export const useBackupInfoQuery = () =>
    useQuery({
        queryKey: ['ai-backup-info'],
        queryFn: fetchBackupInfo,
        staleTime: 10 * 60 * 1000,
    })

export const useStartBackupMutation = () =>
    useMutation({
        mutationFn: (body: CreateBackupBody) =>
            fetch<BackupJob>('/ai/backup/jobs', {
                method: 'POST',
                body,
            }),
    })

export const useCancelBackupMutation = () =>
    useMutation({
        mutationFn: (jobId: string) =>
            fetch(`/ai/backup/jobs/${jobId}`, {
                method: 'DELETE',
            }),
    })

export const useBackupJobQuery = (jobId: string | null, enabled: boolean) =>
    useQuery({
        queryKey: ['ai-backup-job', jobId],
        queryFn: () => fetchBackupJob(jobId as string),
        enabled: enabled && !!jobId,
        // Poll every ~1s while the job is active — nginx is out of the
        // picture because each individual poll is a short request.
        refetchInterval: (q) => {
            const data = q.state.data as BackupJob | undefined
            if (!data) return 1000
            if (
                data.status === 'succeeded' ||
                data.status === 'failed' ||
                data.status === 'cancelled'
            ) {
                return false
            }
            return 1000
        },
    })

export const buildBackupDownloadUrl = (jobId: string): string =>
    `/api/ai/backup/jobs/${jobId}/download`

// The download endpoint is protected by SudoAdminDep, so a plain <a href>
// navigation cannot attach the bearer token and would receive 401. We fetch
// the artefact as a blob with the auth header and trigger the download via
// an object URL instead.
const parseFilenameFromContentDisposition = (
    header: string | null,
): string | null => {
    if (!header) return null
    const utf8Match = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header)
    if (utf8Match?.[1]) {
        try {
            return decodeURIComponent(utf8Match[1].trim())
        } catch {
            return utf8Match[1].trim()
        }
    }
    const asciiMatch = /filename\s*=\s*"?([^";]+)"?/i.exec(header)
    if (asciiMatch?.[1]) return asciiMatch[1].trim()
    return null
}

export const downloadBackupJobArtefact = async (
    jobId: string,
    fallbackName = 'backup',
): Promise<void> => {
    const baseUrl = (import.meta.env.VITE_BASE_API ?? '').replace(/\/$/, '')
    const url = `${baseUrl}/ai/backup/jobs/${jobId}/download`
    const token = useAuth.getState().getAuthToken()
    const res = await window.fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`
        try {
            const body = await res.json()
            if (body?.detail) detail = String(body.detail)
        } catch {
            // ignore — non-JSON error bodies are fine.
        }
        throw new Error(detail)
    }
    const blob = await res.blob()
    const filename =
        parseFilenameFromContentDisposition(
            res.headers.get('content-disposition'),
        ) ?? fallbackName
    const objectUrl = URL.createObjectURL(blob)
    try {
        const link = document.createElement('a')
        link.href = objectUrl
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
    } finally {
        // Give the browser a tick to start the download before revoking.
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    }
}

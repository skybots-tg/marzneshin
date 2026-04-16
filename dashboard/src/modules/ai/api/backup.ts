import { useMutation, useQuery } from '@tanstack/react-query'
import { fetch } from '@marzneshin/common/utils/fetch'

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

export interface BackupDownloadTicket {
    ticket: string
    url: string
    expires_in: number
}

// The plain /download endpoint is bearer-protected, so <a href> navigation
// (which cannot attach an Authorization header) would fail with 401. We
// exchange the admin's session for a one-shot ticket URL and let the
// browser download it natively — that gives us real download progress,
// correct filename from Content-Disposition, and no memory pressure from
// buffering gigabyte dumps into a Blob.
export const requestBackupDownloadTicket = (
    jobId: string,
): Promise<BackupDownloadTicket> =>
    fetch<BackupDownloadTicket>(`/ai/backup/jobs/${jobId}/download-ticket`, {
        method: 'POST',
    })

export const downloadBackupJobArtefact = async (
    job: BackupJob,
): Promise<void> => {
    const { url } = await requestBackupDownloadTicket(job.id)
    const link = document.createElement('a')
    link.href = url
    // The server sets Content-Disposition so the filename is authoritative;
    // empty `download` just tells the browser to treat this as a download
    // rather than a navigation in case the server didn't.
    link.download = ''
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
}

import { FC, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    Button,
    Checkbox,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Label,
    Progress,
    RadioGroup,
    RadioGroupItem,
} from '@marzneshin/common/components/ui'
import {
    Archive,
    CheckCircle2,
    Download,
    Loader2,
    XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import {
    downloadBackupJobArtefact,
    useBackupInfoQuery,
    useBackupJobQuery,
    useCancelBackupMutation,
    useStartBackupMutation,
    type BackupJob,
    type BackupMode,
} from '../api/backup'

interface BackupDialogProps {
    open: boolean
    onClose: () => void
}

const HISTORY_PRESETS = [7, 30, 90, 365] as const

const formatBytes = (n: number): string => {
    if (!n || n < 1024) return `${n} B`
    const units = ['KiB', 'MiB', 'GiB', 'TiB']
    let v = n / 1024
    let i = 0
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024
        i++
    }
    return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`
}

export const BackupDialog: FC<BackupDialogProps> = ({ open, onClose }) => {
    const { t } = useTranslation()

    const { data: info } = useBackupInfoQuery()
    const startMutation = useStartBackupMutation()
    const cancelMutation = useCancelBackupMutation()

    const [mode, setMode] = useState<BackupMode>('light')
    const [historyDays, setHistoryDays] = useState<number>(30)
    const [skipTables, setSkipTables] = useState<Set<string>>(new Set())
    const [jobId, setJobId] = useState<string | null>(null)
    const [isDownloading, setIsDownloading] = useState(false)

    const jobQuery = useBackupJobQuery(jobId, open)
    const job: BackupJob | undefined = jobQuery.data

    useEffect(() => {
        if (!open) return
        // Reset form only when we open a fresh dialog with no active job.
        if (!jobId) {
            setMode('light')
            setHistoryDays(info?.default_history_days ?? 30)
            setSkipTables(new Set())
        }
    }, [open, jobId, info])

    const historyEnabled = mode !== 'config'

    const toggleSkipTable = (table: string) => {
        setSkipTables((prev) => {
            const next = new Set(prev)
            if (next.has(table)) next.delete(table)
            else next.add(table)
            return next
        })
    }

    const handleStart = async () => {
        try {
            const res = await startMutation.mutateAsync({
                mode,
                history_days: historyEnabled ? historyDays : null,
                skip_tables: Array.from(skipTables),
            })
            setJobId(res.id)
        } catch (err) {
            const detail =
                (err as { data?: { detail?: string } })?.data?.detail ||
                String(err)
            toast.error(detail)
        }
    }

    const handleCancel = async () => {
        if (!jobId) return
        try {
            await cancelMutation.mutateAsync(jobId)
            toast.message(t('ai.backup.cancel-requested'))
        } catch (err) {
            const detail =
                (err as { data?: { detail?: string } })?.data?.detail ||
                String(err)
            toast.error(detail)
        }
    }

    const handleDownload = async () => {
        if (!jobId) return
        try {
            setIsDownloading(true)
            await downloadBackupJobArtefact(jobId)
        } catch (err) {
            toast.error(
                err instanceof Error ? err.message : String(err),
            )
        } finally {
            setIsDownloading(false)
        }
    }

    const handleClose = () => {
        // Don't block closing the dialog during a running job — the job
        // keeps running on the server and we can poll it again later.
        setJobId(null)
        onClose()
    }

    const isRunning = job && (job.status === 'pending' || job.status === 'running')
    const isDone = job && job.status === 'succeeded'
    const isFailed = job && job.status === 'failed'
    const isCancelled = job && job.status === 'cancelled'

    const headerProgress = useMemo(() => {
        if (!job) return 0
        if (isDone) return 100
        return Math.max(0, Math.min(100, job.percent))
    }, [job, isDone])

    const phaseLabel = useMemo(() => {
        if (!job) return ''
        const key = `ai.backup.phase.${job.phase}`
        const translated = t(key, { defaultValue: job.phase })
        return translated
    }, [job, t])

    return (
        <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
            <DialogContent className="max-w-lg">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Archive className="size-4" />
                        {t('ai.backup.title')}
                    </DialogTitle>
                    <DialogDescription>
                        {t('ai.backup.description')}
                    </DialogDescription>
                </DialogHeader>

                {!job && (
                    <div className="space-y-5">
                        <div className="space-y-2">
                            <Label className="text-xs font-medium">
                                {t('ai.backup.mode-label')}
                            </Label>
                            <RadioGroup
                                value={mode}
                                onValueChange={(v) => setMode(v as BackupMode)}
                                className="gap-2"
                            >
                                {(['light', 'full', 'config'] as BackupMode[]).map(
                                    (m) => (
                                        <label
                                            key={m}
                                            className="flex items-start gap-3 p-3 rounded-md border border-border/50 hover:border-border cursor-pointer"
                                        >
                                            <RadioGroupItem value={m} />
                                            <div className="space-y-1">
                                                <div className="text-sm font-medium">
                                                    {t(`ai.backup.mode.${m}.title`)}
                                                </div>
                                                <div className="text-xs text-muted-foreground">
                                                    {t(`ai.backup.mode.${m}.description`)}
                                                </div>
                                            </div>
                                        </label>
                                    ),
                                )}
                            </RadioGroup>
                        </div>

                        {historyEnabled && (
                            <div className="space-y-2">
                                <Label className="text-xs font-medium">
                                    {t('ai.backup.history-label')}
                                </Label>
                                <div className="flex flex-wrap items-center gap-2">
                                    {HISTORY_PRESETS.map((d) => (
                                        <button
                                            key={d}
                                            type="button"
                                            onClick={() => setHistoryDays(d)}
                                            className={
                                                historyDays === d
                                                    ? 'px-3 py-1 rounded-md text-xs bg-primary text-primary-foreground'
                                                    : 'px-3 py-1 rounded-md text-xs bg-secondary hover:bg-secondary/80'
                                            }
                                        >
                                            {t('ai.backup.history-days', {
                                                count: d,
                                            })}
                                        </button>
                                    ))}
                                    <div className="flex items-center gap-1">
                                        <Input
                                            type="number"
                                            value={historyDays}
                                            min={1}
                                            max={3650}
                                            onChange={(e) =>
                                                setHistoryDays(
                                                    Math.max(
                                                        1,
                                                        Number(e.target.value) || 1,
                                                    ),
                                                )
                                            }
                                            className="h-8 w-20 text-xs"
                                        />
                                        <span className="text-xs text-muted-foreground">
                                            {t('ai.backup.days')}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {info?.heavy_history_tables?.length ? (
                            <div className="space-y-2">
                                <Label className="text-xs font-medium">
                                    {t('ai.backup.skip-tables-label')}
                                </Label>
                                <p className="text-xs text-muted-foreground">
                                    {t('ai.backup.skip-tables-hint')}
                                </p>
                                <div className="grid grid-cols-2 gap-1">
                                    {info.heavy_history_tables.map((tbl) => {
                                        const id = `skip-${tbl}`
                                        return (
                                            <label
                                                key={tbl}
                                                htmlFor={id}
                                                className="flex items-center gap-2 text-xs cursor-pointer"
                                            >
                                                <Checkbox
                                                    id={id}
                                                    checked={skipTables.has(tbl)}
                                                    onCheckedChange={() =>
                                                        toggleSkipTable(tbl)
                                                    }
                                                />
                                                <code className="font-mono">{tbl}</code>
                                            </label>
                                        )
                                    })}
                                </div>
                            </div>
                        ) : null}
                    </div>
                )}

                {job && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <div className="flex items-center justify-between text-xs">
                                <span className="font-medium">
                                    {t(`ai.backup.status.${job.status}`)}
                                </span>
                                <span className="text-muted-foreground">
                                    {Math.round(headerProgress)}%
                                </span>
                            </div>
                            <Progress value={headerProgress} />
                            <div className="text-xs text-muted-foreground space-y-0.5">
                                {job.strategy && (
                                    <div>
                                        {t('ai.backup.strategy-line', {
                                            strategy: job.strategy,
                                        })}
                                    </div>
                                )}
                                {phaseLabel && (
                                    <div>
                                        {t('ai.backup.phase-line', {
                                            phase: phaseLabel,
                                        })}
                                    </div>
                                )}
                                {job.total_tables > 0 && (
                                    <div>
                                        {t('ai.backup.table-line', {
                                            current: job.current_table_index,
                                            total: job.total_tables,
                                            table: job.table ?? '—',
                                        })}
                                    </div>
                                )}
                                {job.rows_written_table > 0 && (
                                    <div>
                                        {t('ai.backup.rows-line', {
                                            written: job.rows_written_table.toLocaleString(),
                                            expected:
                                                job.expected_rows_table > 0
                                                    ? job.expected_rows_table.toLocaleString()
                                                    : '—',
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>

                        {isFailed && (
                            <div className="flex items-start gap-2 p-3 rounded-md bg-destructive/10 border border-destructive/30 text-sm text-destructive">
                                <XCircle className="size-4 mt-0.5" />
                                <div className="space-y-1">
                                    <div className="font-medium">
                                        {t('ai.backup.failed')}
                                    </div>
                                    <div className="text-xs">
                                        {job.error || '—'}
                                    </div>
                                </div>
                            </div>
                        )}

                        {isCancelled && (
                            <div className="text-sm text-muted-foreground">
                                {t('ai.backup.cancelled-note')}
                            </div>
                        )}

                        {isDone && (
                            <div className="flex items-start gap-2 p-3 rounded-md bg-green-500/10 border border-green-500/30 text-sm text-green-700 dark:text-green-400">
                                <CheckCircle2 className="size-4 mt-0.5" />
                                <div className="space-y-1">
                                    <div className="font-medium">
                                        {t('ai.backup.succeeded')}
                                    </div>
                                    <div className="text-xs">
                                        {t('ai.backup.size-line', {
                                            size: formatBytes(job.bytes_written),
                                        })}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                <DialogFooter>
                    {!job && (
                        <>
                            <Button variant="outline" onClick={handleClose}>
                                {t('ai.backup.cancel')}
                            </Button>
                            <Button
                                onClick={handleStart}
                                disabled={startMutation.isPending}
                            >
                                {startMutation.isPending && (
                                    <Loader2 className="size-3.5 animate-spin mr-1" />
                                )}
                                {t('ai.backup.start')}
                            </Button>
                        </>
                    )}

                    {isRunning && (
                        <>
                            <Button
                                variant="outline"
                                onClick={handleCancel}
                                disabled={cancelMutation.isPending || job?.cancel_requested}
                            >
                                {job?.cancel_requested
                                    ? t('ai.backup.cancel-pending')
                                    : t('ai.backup.stop')}
                            </Button>
                            <Button variant="secondary" onClick={handleClose}>
                                {t('ai.backup.hide')}
                            </Button>
                        </>
                    )}

                    {(isDone || isFailed || isCancelled) && (
                        <>
                            {isDone && jobId && (
                                <Button
                                    onClick={handleDownload}
                                    disabled={isDownloading}
                                >
                                    {isDownloading ? (
                                        <Loader2 className="size-3.5 animate-spin mr-1" />
                                    ) : (
                                        <Download className="size-3.5 mr-1" />
                                    )}
                                    {t('ai.backup.download')}
                                </Button>
                            )}
                            <Button variant="outline" onClick={() => setJobId(null)}>
                                {t('ai.backup.new-backup')}
                            </Button>
                            <Button variant="secondary" onClick={handleClose}>
                                {t('ai.backup.close')}
                            </Button>
                        </>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

import { FC, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    Button,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Label,
    Textarea,
} from '@marzneshin/common/components/ui'
import { KeyRound, ShieldAlert, ShieldCheck, Terminal } from 'lucide-react'
import { toast } from 'sonner'
import {
    fetchSSHStatus,
    useSSHSaveCredentialsMutation,
    useSSHUnlockMutation,
    type SSHStatus,
} from '../api/ssh'

interface SSHUnlockDialogProps {
    open: boolean
    sessionId: string | null
    nodeId: number | null
    toolName: string
    onUnlocked: () => void
    onCancel: () => void
}

type AuthMode = 'password' | 'key'

const PIN_LENGTH = 4

export const SSHUnlockDialog: FC<SSHUnlockDialogProps> = ({
    open,
    sessionId,
    nodeId,
    toolName,
    onUnlocked,
    onCancel,
}) => {
    const { t } = useTranslation()
    const [status, setStatus] = useState<SSHStatus | null>(null)
    const [statusLoading, setStatusLoading] = useState(false)
    const [statusError, setStatusError] = useState<string | null>(null)

    const [pin, setPin] = useState('')
    const [sshUser, setSSHUser] = useState('root')
    const [sshPort, setSSHPort] = useState(22)
    const [authMode, setAuthMode] = useState<AuthMode>('password')
    const [sshPassword, setSSHPassword] = useState('')
    const [sshKey, setSSHKey] = useState('')

    const unlockMutation = useSSHUnlockMutation()
    const saveMutation = useSSHSaveCredentialsMutation()

    const needsCredentials = useMemo(
        () => status?.pin_configured && !status?.credentials_saved,
        [status],
    )

    useEffect(() => {
        if (!open || !sessionId) return
        setStatus(null)
        setStatusError(null)
        setPin('')
        setSSHPassword('')
        setSSHKey('')
        setStatusLoading(true)
        fetchSSHStatus(sessionId, nodeId ?? undefined)
            .then((s) => setStatus(s))
            .catch((err) => {
                setStatusError(String(err?.message || err))
            })
            .finally(() => setStatusLoading(false))
    }, [open, sessionId, nodeId])

    const pinValid = /^\d{4}$/.test(pin)

    const canSubmit = useMemo(() => {
        if (!pinValid) return false
        if (needsCredentials) {
            if (!sshUser.trim() || sshPort < 1 || sshPort > 65535) return false
            if (authMode === 'password' && !sshPassword) return false
            if (authMode === 'key' && !sshKey.trim()) return false
        }
        return true
    }, [pinValid, needsCredentials, sshUser, sshPort, authMode, sshPassword, sshKey])

    const handleSubmit = async () => {
        if (!sessionId || !canSubmit) return
        try {
            if (needsCredentials && nodeId != null) {
                await saveMutation.mutateAsync({
                    session_id: sessionId,
                    node_id: nodeId,
                    pin,
                    ssh_user: sshUser.trim(),
                    ssh_port: sshPort,
                    ssh_password: authMode === 'password' ? sshPassword : undefined,
                    ssh_key: authMode === 'key' ? sshKey : undefined,
                })
            } else {
                await unlockMutation.mutateAsync({
                    session_id: sessionId,
                    pin,
                })
            }
            toast.success(t('ai.ssh.unlocked-toast'))
            onUnlocked()
        } catch (err) {
            const message = (err as { data?: { detail?: string } })?.data?.detail
                || String(err)
            toast.error(message)
        }
    }

    const loading = statusLoading || unlockMutation.isPending || saveMutation.isPending

    return (
        <Dialog open={open} onOpenChange={(v) => { if (!v) onCancel() }}>
            <DialogContent className="max-w-lg">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Terminal className="size-4" />
                        {t('ai.ssh.title')}
                    </DialogTitle>
                    <DialogDescription>
                        {t('ai.ssh.description', { tool: toolName })}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                    {statusLoading && (
                        <div className="text-sm text-muted-foreground">
                            {t('ai.ssh.loading-status')}
                        </div>
                    )}

                    {statusError && (
                        <div className="flex items-start gap-2 p-3 rounded-md bg-destructive/10 border border-destructive/30 text-sm text-destructive">
                            <ShieldAlert className="size-4 mt-0.5" />
                            <span>{statusError}</span>
                        </div>
                    )}

                    {status && !status.pin_configured && (
                        <div className="flex items-start gap-2 p-3 rounded-md bg-amber-500/10 border border-amber-500/30 text-sm text-amber-700 dark:text-amber-400">
                            <ShieldAlert className="size-4 mt-0.5" />
                            <span>{t('ai.ssh.pin-not-configured')}</span>
                        </div>
                    )}

                    {status?.pin_configured && (
                        <>
                            {status.node_address && (
                                <div className="text-xs text-muted-foreground">
                                    {t('ai.ssh.target', {
                                        address: status.node_address,
                                        id: nodeId,
                                    })}
                                </div>
                            )}

                            {needsCredentials && (
                                <div className="space-y-3 p-3 rounded-md border border-border/50 bg-muted/20">
                                    <div className="flex items-center gap-2 text-xs font-medium">
                                        <KeyRound className="size-3.5" />
                                        {t('ai.ssh.new-credentials')}
                                    </div>

                                    <div className="grid grid-cols-[1fr_110px] gap-2">
                                        <div>
                                            <Label className="text-xs">{t('ai.ssh.user')}</Label>
                                            <Input
                                                value={sshUser}
                                                onChange={(e) => setSSHUser(e.target.value)}
                                                placeholder="root"
                                            />
                                        </div>
                                        <div>
                                            <Label className="text-xs">{t('ai.ssh.port')}</Label>
                                            <Input
                                                type="number"
                                                value={sshPort}
                                                onChange={(e) => setSSHPort(Number(e.target.value) || 0)}
                                                min={1}
                                                max={65535}
                                            />
                                        </div>
                                    </div>

                                    <div className="flex gap-2 text-xs">
                                        <button
                                            type="button"
                                            onClick={() => setAuthMode('password')}
                                            className={
                                                authMode === 'password'
                                                    ? 'px-3 py-1 rounded-md bg-primary text-primary-foreground'
                                                    : 'px-3 py-1 rounded-md bg-secondary hover:bg-secondary/80'
                                            }
                                        >
                                            {t('ai.ssh.password-auth')}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setAuthMode('key')}
                                            className={
                                                authMode === 'key'
                                                    ? 'px-3 py-1 rounded-md bg-primary text-primary-foreground'
                                                    : 'px-3 py-1 rounded-md bg-secondary hover:bg-secondary/80'
                                            }
                                        >
                                            {t('ai.ssh.key-auth')}
                                        </button>
                                    </div>

                                    {authMode === 'password' ? (
                                        <div>
                                            <Label className="text-xs">{t('ai.ssh.password')}</Label>
                                            <Input
                                                type="password"
                                                value={sshPassword}
                                                onChange={(e) => setSSHPassword(e.target.value)}
                                                autoComplete="new-password"
                                            />
                                        </div>
                                    ) : (
                                        <div>
                                            <Label className="text-xs">
                                                {t('ai.ssh.private-key')}
                                            </Label>
                                            <Textarea
                                                value={sshKey}
                                                onChange={(e) => setSSHKey(e.target.value)}
                                                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----\n..."
                                                rows={5}
                                                className="font-mono text-xs"
                                            />
                                        </div>
                                    )}

                                    <p className="text-xs text-muted-foreground">
                                        {t('ai.ssh.saved-hint')}
                                    </p>
                                </div>
                            )}

                            {status.credentials_saved && (
                                <div className="flex items-center gap-2 text-xs text-green-600 dark:text-green-400">
                                    <ShieldCheck className="size-3.5" />
                                    {t('ai.ssh.credentials-saved-hint')}
                                </div>
                            )}

                            <div>
                                <Label className="text-xs">{t('ai.ssh.pin')}</Label>
                                <Input
                                    type="password"
                                    value={pin}
                                    inputMode="numeric"
                                    maxLength={PIN_LENGTH}
                                    onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, PIN_LENGTH))}
                                    placeholder="••••"
                                    autoComplete="one-time-code"
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && canSubmit && !loading) {
                                            e.preventDefault()
                                            handleSubmit()
                                        }
                                    }}
                                />
                            </div>
                        </>
                    )}
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={onCancel} disabled={loading}>
                        {t('ai.ssh.cancel')}
                    </Button>
                    <Button
                        onClick={handleSubmit}
                        disabled={!canSubmit || loading || !status?.pin_configured}
                    >
                        {needsCredentials ? t('ai.ssh.save-and-unlock') : t('ai.ssh.unlock')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

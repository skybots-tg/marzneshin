import { FC } from 'react'
import { useTranslation } from 'react-i18next'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@marzneshin/common/components/ui'
import { ShieldCheck } from 'lucide-react'
import type { PendingConfirmation } from '../types'

interface ConfirmationDialogProps {
    pending: PendingConfirmation | null
    onApprove: () => void
    onApproveAll: () => void
    onReject: () => void
    loading: boolean
}

export const ConfirmationDialog: FC<ConfirmationDialogProps> = ({
    pending,
    onApprove,
    onApproveAll,
    onReject,
    loading,
}) => {
    const { t } = useTranslation()

    if (!pending) return null

    return (
        <AlertDialog open={!!pending}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{t('ai.confirm-title')}</AlertDialogTitle>
                    <AlertDialogDescription>
                        {t('ai.confirm-description')}
                    </AlertDialogDescription>
                </AlertDialogHeader>

                <div className="my-3 p-3 rounded-md bg-muted/50 border border-border/50">
                    <div className="font-medium text-sm mb-2">{pending.tool_name}</div>
                    <pre className="text-xs bg-background rounded p-2 overflow-x-auto max-h-48">
                        {JSON.stringify(pending.tool_args, null, 2)}
                    </pre>
                </div>

                <p className="text-xs text-muted-foreground -mt-1">
                    {t('ai.approve-all-hint')}
                </p>

                <AlertDialogFooter className="gap-2">
                    <Button
                        variant="outline"
                        onClick={onReject}
                        disabled={loading}
                    >
                        {t('ai.reject')}
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={onApproveAll}
                        disabled={loading}
                        title={t('ai.approve-all-hint')}
                    >
                        <ShieldCheck className="size-4 mr-1" />
                        {t('ai.approve-all')}
                    </Button>
                    <Button onClick={onApprove} disabled={loading}>
                        {t('ai.approve')}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

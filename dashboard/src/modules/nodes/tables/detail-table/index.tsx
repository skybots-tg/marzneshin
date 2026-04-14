import { FC } from 'react'
import { NodeType, NodesStatus, NodesStatusBadge } from '../..'
import { useTranslation } from 'react-i18next'

interface NodesDetailTableProps {
    node: NodeType
}

const DetailRow: FC<{ label: string; value: React.ReactNode; last?: boolean }> = ({ label, value, last }) => (
    <div className={`flex items-center justify-between py-3 ${last ? '' : 'border-b border-border/30'}`}>
        <span className="text-[13px] text-muted-foreground">{label}</span>
        <span className="text-[13px] font-medium text-foreground">{value}</span>
    </div>
)

export const NodesDetailTable: FC<NodesDetailTableProps> = ({ node }) => {
    const { t } = useTranslation()
    const hasError = node.status === 'unhealthy' && node.message;

    return (
        <div className="rounded-xl bg-secondary/40 border border-border/30 px-4">
            <DetailRow label={t('name')} value={node.name} />
            <DetailRow
                label={t('address')}
                value={
                    <span className="font-mono text-xs">{node.address}:{node.port}</span>
                }
            />
            <DetailRow
                label={t('page.nodes.usage_coefficient')}
                value={
                    <span className="tabular-nums">{node.usage_coefficient}</span>
                }
            />
            <DetailRow
                label={t('status')}
                value={<NodesStatusBadge status={NodesStatus[node.status]} />}
                last={!hasError}
            />
            {hasError && (
                <DetailRow
                    label={t('page.nodes.error_reason')}
                    value={
                        <span className="text-destructive text-xs max-w-[60%] text-right">{node.message}</span>
                    }
                    last
                />
            )}
        </div>
    )
}

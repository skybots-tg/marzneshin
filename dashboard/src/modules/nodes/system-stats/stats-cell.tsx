import { FC } from "react";
import { Cpu, MemoryStick, HardDrive, ServerOff } from "lucide-react";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@marzneshin/common/components";
import { cn } from "@marzneshin/common/utils";
import { useTranslation } from "react-i18next";
import {
    NodeType,
    useNodeSystemStatsQuery,
    NodeSystemStatsType,
} from "@marzneshin/modules/nodes";
import {
    formatBytes,
    formatPercent,
    formatUptime,
    utilizationColor,
} from "./format";

const isHealthy = (node: NodeType) =>
    node.status === "healthy" || node.status === "unhealthy";

type MetricRowProps = {
    icon: React.ReactNode;
    percent: number;
    label: string;
};

const MetricRow: FC<MetricRowProps> = ({ icon, percent, label }) => {
    const { text, bar } = utilizationColor(percent);
    const safePct = Math.max(0, Math.min(100, percent || 0));
    return (
        <div className="flex items-center gap-1.5 text-xs leading-none">
            <span className="text-muted-foreground">{icon}</span>
            <div className="relative h-1.5 w-14 rounded-full bg-secondary/70 overflow-hidden">
                <div
                    className={cn("h-full rounded-full transition-all", bar)}
                    style={{ width: `${safePct}%` }}
                />
            </div>
            <span className={cn("tabular-nums w-9 text-right", text)} title={label}>
                {formatPercent(percent)}
            </span>
        </div>
    );
};

const StatsTooltip: FC<{ stats: NodeSystemStatsType }> = ({ stats }) => {
    const { t } = useTranslation();
    return (
        <div className="space-y-1.5 text-xs">
            <div className="flex justify-between gap-6">
                <span className="text-muted-foreground">{t('page.nodes.system.cpu')}</span>
                <span className="tabular-nums">
                    {formatPercent(stats.cpu_percent)} · {stats.cpu_count} {t('page.nodes.system.cores')}
                </span>
            </div>
            <div className="flex justify-between gap-6">
                <span className="text-muted-foreground">{t('page.nodes.system.ram')}</span>
                <span className="tabular-nums">
                    {formatBytes(stats.mem_used)} / {formatBytes(stats.mem_total)} ({formatPercent(stats.mem_percent)})
                </span>
            </div>
            <div className="flex justify-between gap-6">
                <span className="text-muted-foreground">{t('page.nodes.system.disk')}</span>
                <span className="tabular-nums">
                    {formatBytes(stats.disk_used)} / {formatBytes(stats.disk_total)} ({formatPercent(stats.disk_percent)})
                </span>
            </div>
            {stats.disk_path && (
                <div className="flex justify-between gap-6">
                    <span className="text-muted-foreground">{t('page.nodes.system.disk_path')}</span>
                    <span className="font-mono text-[10px]">{stats.disk_path}</span>
                </div>
            )}
            <div className="flex justify-between gap-6">
                <span className="text-muted-foreground">{t('page.nodes.system.load_avg')}</span>
                <span className="tabular-nums">
                    {stats.load_avg_1.toFixed(2)} · {stats.load_avg_5.toFixed(2)} · {stats.load_avg_15.toFixed(2)}
                </span>
            </div>
            <div className="flex justify-between gap-6">
                <span className="text-muted-foreground">{t('page.nodes.system.uptime')}</span>
                <span className="tabular-nums">{formatUptime(stats.uptime_seconds)}</span>
            </div>
            <div className="text-[10px] text-muted-foreground/70 pt-1 border-t border-border/30">
                {t('page.nodes.system.cached_hint')}
            </div>
        </div>
    );
};

export const SystemStatsCell: FC<{ node: NodeType }> = ({ node }) => {
    const { t } = useTranslation();
    const enabled = isHealthy(node);
    const { data, isFetching } = useNodeSystemStatsQuery(node.id, { enabled });

    if (!enabled) {
        return (
            <span className="text-xs text-muted-foreground inline-flex items-center gap-1.5">
                <ServerOff className="size-3" />
                {t('page.nodes.system.offline')}
            </span>
        );
    }

    if (!data) {
        return (
            <span className="text-xs text-muted-foreground">
                {isFetching ? t('page.nodes.system.loading') : "—"}
            </span>
        );
    }

    if (data.status === "unsupported") {
        return (
            <TooltipProvider>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <span className="text-xs text-muted-foreground italic underline decoration-dotted underline-offset-2">
                            {t('page.nodes.system.unsupported_short')}
                        </span>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs">
                        <p>{t('page.nodes.system.unsupported_desc')}</p>
                    </TooltipContent>
                </Tooltip>
            </TooltipProvider>
        );
    }

    if (data.status !== "ok" || !data.stats) {
        return (
            <span className="text-xs text-muted-foreground">
                {t('page.nodes.system.unavailable')}
            </span>
        );
    }

    const stats = data.stats;

    return (
        <TooltipProvider delayDuration={150}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <div className="flex flex-col gap-1 cursor-default w-fit">
                        <MetricRow
                            icon={<Cpu className="size-3" />}
                            percent={stats.cpu_percent}
                            label="CPU"
                        />
                        <MetricRow
                            icon={<MemoryStick className="size-3" />}
                            percent={stats.mem_percent}
                            label="RAM"
                        />
                        <MetricRow
                            icon={<HardDrive className="size-3" />}
                            percent={stats.disk_percent}
                            label="Disk"
                        />
                    </div>
                </TooltipTrigger>
                <TooltipContent side="left" className="min-w-[260px]">
                    <StatsTooltip stats={stats} />
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};

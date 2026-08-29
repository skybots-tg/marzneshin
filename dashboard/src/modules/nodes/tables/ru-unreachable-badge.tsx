import { FC } from "react";
import { AlertTriangle } from "lucide-react";
import {
    Badge,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@marzneshin/common/components";
import i18n from "@marzneshin/features/i18n";
import type { NodeType } from "@marzneshin/modules/nodes";

const formatAge = (seconds: number): string => {
    const minutes = Math.max(0, Math.round(seconds / 60));
    if (minutes < 90) return i18n.t("page.nodes.ru_unreachable.age_min", { total: minutes });
    return i18n.t("page.nodes.ru_unreachable.age_hour", { total: Math.round(minutes / 60) });
};

/**
 * "Nobody in Russia can use this node", when the audit can actually say so.
 *
 * The status column next to it is the panel's own view from Norway, and the two
 * disagree by design: a node the panel talks to every second can be unreachable
 * from every Russian network at once. Only the audit probes from RU vantages,
 * so this is the only place that answer exists.
 *
 * Silent unless one whole side of the node is down -- see `node_ru_probe`.
 * A disabled node is left alone: it fails from Russia because it is switched
 * off, which the status badge already says.
 */
export const RuUnreachableBadge: FC<{ node: NodeType }> = ({ node }) => {
    const probe = node.ru_probe;
    if (!probe?.unreachable || node.status === "disabled") return null;

    const detail = probe.reason === "entry"
        ? i18n.t("page.nodes.ru_unreachable.entry", { total: probe.entry_total })
        : probe.reason === "exit"
            ? i18n.t("page.nodes.ru_unreachable.exit", { total: probe.exit_total })
            : i18n.t("page.nodes.ru_unreachable.both", {
                entries: probe.entry_total,
                exits: probe.exit_total,
            });

    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>
                    <span className="inline-flex">
                        <Badge variant="destructive" className="h-6 gap-1">
                            <AlertTriangle className="size-3" />
                            {i18n.t("page.nodes.ru_unreachable.label")}
                        </Badge>
                    </span>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                    <p>{detail}</p>
                    <p className="text-muted-foreground">{formatAge(probe.age_sec)}</p>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};

export default RuUnreachableBadge;

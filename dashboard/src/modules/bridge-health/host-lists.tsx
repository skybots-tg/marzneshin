import { Badge, Button, Card, CardContent } from "@marzneshin/common/components";
import type { FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { EyeOff, Eye, Compass, GitBranch } from "lucide-react";
import type { BridgeGap, BridgeHost } from "./api";

interface SectionProps {
    title: string;
    hint: string;
    icon: ReactNode;
    hosts: BridgeHost[];
    action?: { label: string; onClick: (ids: number[]) => void; busy: boolean };
    render: (h: BridgeHost) => ReactNode;
}

const Section: FC<SectionProps> = ({ title, hint, icon, hosts, action, render }) => {
    if (!hosts.length) return null;
    return (
        <Card>
            <CardContent className="p-3 space-y-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="font-medium flex items-center gap-2">
                        {icon}
                        {title}
                        <Badge variant="secondary">{hosts.length}</Badge>
                    </div>
                    {action && (
                        <Button
                            size="sm"
                            variant="outline"
                            disabled={action.busy}
                            onClick={() => action.onClick(hosts.map((h) => h.host_id))}
                        >
                            {action.label}
                        </Button>
                    )}
                </div>
                <p className="text-xs text-muted-foreground">{hint}</p>
                <ul className="text-sm divide-y">
                    {hosts.map((h) => (
                        <li key={h.host_id} className="py-1.5 flex gap-2 items-center">
                            <span className="text-muted-foreground text-xs w-12 shrink-0">
                                #{h.host_id}
                            </span>
                            <span className="flex-1 truncate">{h.remark}</span>
                            {render(h)}
                        </li>
                    ))}
                </ul>
            </CardContent>
        </Card>
    );
};

interface Props {
    hosts: BridgeHost[];
    gaps: BridgeGap[];
    shadowed: number[];
    busy: boolean;
    onApply: (body: { disable_ids?: number[]; enable_ids?: number[] }) => void;
}

export const BridgeHostLists: FC<Props> = ({ hosts, gaps, shadowed, busy, onApply }) => {
    const { t } = useTranslation();
    const hidden = new Set(shadowed);
    const dead = hosts.filter((h) => h.verdict === "fail" && !h.is_disabled);
    const revive = hosts.filter(
        (h) => h.verdict === "pass" && h.is_disabled && !hidden.has(h.host_id),
    );
    const retired = hosts.filter((h) => hidden.has(h.host_id));
    const geo = hosts.filter((h) => h.verdict === "wrong_geo");
    const flaky = hosts.filter((h) => h.partial && h.verdict !== "fail");

    return (
        <div className="space-y-4">
            <Section
                title={t("page.bridge_health.dead.title")}
                hint={t("page.bridge_health.dead.hint")}
                icon={<EyeOff className="size-4 text-red-500" />}
                hosts={dead}
                action={{
                    label: t("page.bridge_health.dead.action"),
                    busy,
                    onClick: (ids) => onApply({ disable_ids: ids, enable_ids: [] }),
                }}
                render={(h) => (
                    <Badge variant="destructive" className="shrink-0">
                        {h.error ?? "fail"}
                    </Badge>
                )}
            />
            <Section
                title={t("page.bridge_health.revive.title")}
                hint={t("page.bridge_health.revive.hint")}
                icon={<Eye className="size-4 text-green-500" />}
                hosts={revive}
                action={{
                    label: t("page.bridge_health.revive.action"),
                    busy,
                    onClick: (ids) => onApply({ disable_ids: [], enable_ids: ids }),
                }}
                render={(h) => (
                    <Badge variant="outline" className="shrink-0">
                        {h.country}
                    </Badge>
                )}
            />
            <Section
                title={t("page.bridge_health.retired.title")}
                hint={t("page.bridge_health.retired.hint")}
                icon={<EyeOff className="size-4 text-muted-foreground" />}
                hosts={retired}
                render={(h) => (
                    <Badge variant="outline" className="shrink-0">
                        {h.node_name}
                    </Badge>
                )}
            />
            <Section
                title={t("page.bridge_health.geo.title")}
                hint={t("page.bridge_health.geo.hint")}
                icon={<Compass className="size-4 text-amber-500" />}
                hosts={geo}
                render={(h) => (
                    <Badge variant="outline" className="shrink-0">
                        {h.expected_country} → {h.country}
                    </Badge>
                )}
            />
            <Section
                title={t("page.bridge_health.flaky.title")}
                hint={t("page.bridge_health.flaky.hint")}
                icon={<GitBranch className="size-4 text-amber-500" />}
                hosts={flaky}
                render={(h) => (
                    <Badge variant="outline" className="shrink-0">
                        {h.vantages_ok?.length}/{h.vantages_tried?.length}
                    </Badge>
                )}
            />
            {gaps.length > 0 && (
                <Card>
                    <CardContent className="p-3 space-y-2">
                        <div className="font-medium flex items-center gap-2">
                            <GitBranch className="size-4" />
                            {t("page.bridge_health.gaps.title")}
                            <Badge variant="secondary">{gaps.length}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            {t("page.bridge_health.gaps.hint")}
                        </p>
                        <ul className="text-sm divide-y">
                            {gaps.map((g) => (
                                <li
                                    key={`${g.entry_key}-${g.slot}`}
                                    className="py-1.5 flex gap-2 items-center flex-wrap"
                                >
                                    <Badge variant="default">{g.entry_key.toUpperCase()}</Badge>
                                    <span className="font-medium">{g.slot}</span>
                                    <Badge variant={g.fillable ? "secondary" : "outline"}>
                                        {g.reason}
                                    </Badge>
                                    {g.fillable ? (
                                        <code className="text-xs text-muted-foreground ml-auto">
                                            bridge_audit.py fill {g.entry_key} {g.slot} --apply
                                        </code>
                                    ) : (
                                        <span className="text-xs text-muted-foreground ml-auto">
                                            {t("page.bridge_health.gaps.blocked")}
                                        </span>
                                    )}
                                </li>
                            ))}
                        </ul>
                    </CardContent>
                </Card>
            )}
        </div>
    );
};

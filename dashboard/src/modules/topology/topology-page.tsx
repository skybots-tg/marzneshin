import {
    Page,
    Button,
    Badge,
    Loading,
    Card,
    CardContent,
} from "@marzneshin/common/components";
import { type FC, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, X, Plus, ArrowUpCircle, RefreshCw, Zap } from "lucide-react";
import { fetchTopology, type Topology } from "./api";
import { PromoteDialog } from "./promote-dialog";
import { PlanExitDialog } from "./plan-exit-dialog";

const isoToFlag = (iso: string): string =>
    iso
        .toUpperCase()
        .replace(/./g, (c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65));

export const TopologyPage: FC = () => {
    const { t } = useTranslation();
    const [topo, setTopo] = useState<Topology | null>(null);
    const [loading, setLoading] = useState(true);
    const [promoteOpen, setPromoteOpen] = useState(false);
    const [exitOpen, setExitOpen] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            setTopo(await fetchTopology());
        } catch {
            setTopo(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const isos = topo?.exit_countries ?? [];

    return (
        <Page title={t("topology")}>
            <div className="flex flex-wrap gap-2 mb-4">
                <Button onClick={() => setExitOpen(true)}>
                    <Plus className="size-4 mr-2" />
                    {t("page.topology.add_exit")}
                </Button>
                <Button variant="secondary" onClick={() => setPromoteOpen(true)}>
                    <ArrowUpCircle className="size-4 mr-2" />
                    {t("page.topology.promote_node")}
                </Button>
                <Button variant="outline" onClick={load}>
                    <RefreshCw className="size-4 mr-2" />
                    {t("page.topology.refresh")}
                </Button>
            </div>

            {loading || !topo ? (
                <Loading />
            ) : (
                <div className="space-y-4">
                    <Card>
                        <CardContent className="p-0 overflow-x-auto">
                            <table className="w-full text-sm border-collapse">
                                <thead>
                                    <tr className="border-b">
                                        <th className="text-left p-2 sticky left-0 bg-card">
                                            {t("page.topology.entry")}
                                        </th>
                                        {isos.map((iso) => (
                                            <th key={iso} className="p-2 text-center" title={iso}>
                                                {isoToFlag(iso)}
                                                <div className="text-[10px] text-muted-foreground">
                                                    {iso}
                                                </div>
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {topo.entries.map((e) => (
                                        <tr key={e.key} className="border-b hover:bg-muted/30">
                                            <td className="p-2 sticky left-0 bg-card whitespace-nowrap">
                                                <Badge
                                                    variant={
                                                        e.tier === "universal" ? "default" : "secondary"
                                                    }
                                                    className="mr-2"
                                                >
                                                    {e.key.toUpperCase()}
                                                </Badge>
                                                <span className="text-muted-foreground">{e.name}</span>
                                            </td>
                                            {isos.map((iso) => {
                                                const has = e.exit_isos.includes(iso);
                                                return (
                                                    <td key={iso} className="p-2 text-center">
                                                        {has ? (
                                                            <Check className="size-4 text-green-500 inline" />
                                                        ) : (
                                                            <X className="size-4 text-red-400/60 inline" />
                                                        )}
                                                    </td>
                                                );
                                            })}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardContent className="p-3">
                            <div className="font-medium mb-2 flex items-center gap-2">
                                <Zap className="size-4 text-yellow-500" />
                                {t("page.topology.fast_exits")}
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {topo.fast.length === 0 && (
                                    <span className="text-sm text-muted-foreground">—</span>
                                )}
                                {topo.fast.map((f) => (
                                    <Badge key={f.iso} variant="outline">
                                        {isoToFlag(f.iso)} {f.label} · {f.node_count}
                                    </Badge>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}

            {topo && (
                <>
                    <PromoteDialog
                        open={promoteOpen}
                        onOpenChange={setPromoteOpen}
                        donors={topo.donor_nodes}
                        candidates={topo.promote_candidates}
                        onDone={load}
                    />
                    <PlanExitDialog
                        open={exitOpen}
                        onOpenChange={setExitOpen}
                        nodes={[
                            ...topo.promote_candidates,
                            ...topo.donor_nodes.map((d) => ({
                                node_id: d.node_id,
                                name: d.name,
                            })),
                        ]}
                    />
                </>
            )}
        </Page>
    );
};

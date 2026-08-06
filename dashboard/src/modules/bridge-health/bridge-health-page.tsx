import {
    Page,
    Button,
    Badge,
    Loading,
    Card,
    CardContent,
} from "@marzneshin/common/components";
import { type FC, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, Radar, ShieldCheck, AlertTriangle } from "lucide-react";
import {
    applyBridgeHealth,
    fetchBridgeHealth,
    fetchBridgeScanLog,
    startBridgeScan,
    type BridgeHealthReport,
} from "./api";
import { BridgeMatrix, MatrixLegend } from "./matrix";
import { BridgeHostLists } from "./host-lists";

const humanAge = (sec: number): string => {
    if (sec < 90) return `${sec}s`;
    if (sec < 5400) return `${Math.round(sec / 60)}m`;
    return `${Math.round(sec / 3600)}h`;
};

export const BridgeHealthPage: FC = () => {
    const { t } = useTranslation();
    const [report, setReport] = useState<BridgeHealthReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [log, setLog] = useState<string[]>([]);
    const poll = useRef<number | null>(null);

    const load = useCallback(async () => {
        try {
            setReport(await fetchBridgeHealth());
        } catch {
            setReport(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    // While a scan runs, tail its log and refresh the report when it lands.
    useEffect(() => {
        if (!report?.scan_running) {
            if (poll.current) window.clearInterval(poll.current);
            poll.current = null;
            return;
        }
        poll.current = window.setInterval(async () => {
            try {
                const l = await fetchBridgeScanLog();
                setLog(l.lines.slice(-14));
                if (!l.running) load();
            } catch {
                /* keep polling */
            }
        }, 4000);
        return () => {
            if (poll.current) window.clearInterval(poll.current);
        };
    }, [report?.scan_running, load]);

    const runScan = async () => {
        setBusy(true);
        setMessage(null);
        const r = await startBridgeScan(false);
        setMessage(
            r.queued
                ? t("page.bridge_health.scan_queued")
                : (r.reason ?? t("page.bridge_health.scan_failed")),
        );
        setBusy(false);
        load();
    };

    const apply = async (body: {
        disable_ids?: number[];
        enable_ids?: number[];
    }) => {
        setBusy(true);
        setMessage(null);
        const r = await applyBridgeHealth(body);
        setMessage(
            r.error ??
                t("page.bridge_health.applied", {
                    hidden: r.disabled?.length ?? 0,
                    restored: r.enabled?.length ?? 0,
                }),
        );
        setBusy(false);
        load();
    };

    const counts = report?.counts ?? {};
    const pending = report?.pending ?? { disable: [], enable: [] };
    const pendingTotal = pending.disable.length + pending.enable.length;

    return (
        <Page title={t("bridge-health")}>
            <div className="flex flex-wrap gap-2 mb-4 items-center">
                <Button onClick={runScan} disabled={busy || report?.scan_running}>
                    <Radar
                        className={`size-4 mr-2 ${report?.scan_running ? "animate-spin" : ""}`}
                    />
                    {report?.scan_running
                        ? t("page.bridge_health.scanning")
                        : t("page.bridge_health.run_scan")}
                </Button>
                <Button
                    variant="secondary"
                    disabled={busy || !pendingTotal || report?.apply_blocked}
                    onClick={() => apply({})}
                >
                    <ShieldCheck className="size-4 mr-2" />
                    {t("page.bridge_health.apply_all", {
                        hide: pending.disable.length,
                        restore: pending.enable.length,
                    })}
                </Button>
                <Button variant="outline" onClick={load} disabled={busy}>
                    <RefreshCw className="size-4 mr-2" />
                    {t("page.bridge_health.refresh")}
                </Button>
                {report?.available && (
                    <span className="text-xs text-muted-foreground ml-auto">
                        {t("page.bridge_health.last_scan", {
                            age: humanAge(report.age_sec ?? 0),
                        })}
                        {report.vantages?.length
                            ? ` · ${t("page.bridge_health.from_vantages", {
                                  list: report.vantages.map((v) => v.name).join(", "),
                              })}`
                            : ""}
                    </span>
                )}
            </div>

            {message && (
                <Card className="mb-4">
                    <CardContent className="p-3 text-sm">{message}</CardContent>
                </Card>
            )}

            {loading ? (
                <Loading />
            ) : !report?.available ? (
                <Card>
                    <CardContent className="p-4 text-sm text-muted-foreground">
                        {report?.hint ?? t("page.bridge_health.unavailable")}
                    </CardContent>
                </Card>
            ) : (
                <div className="space-y-4">
                    <div className="flex flex-wrap gap-2 items-center">
                        <Badge variant="outline">
                            {t("page.bridge_health.total", { n: report.total })}
                        </Badge>
                        <Badge className="bg-green-500/15 text-green-600 hover:bg-green-500/15">
                            {t("page.bridge_health.working", { n: counts.pass ?? 0 })}
                        </Badge>
                        <Badge className="bg-amber-500/15 text-amber-600 hover:bg-amber-500/15">
                            {t("page.bridge_health.wrong_geo", { n: counts.wrong_geo ?? 0 })}
                        </Badge>
                        <Badge variant="destructive">
                            {t("page.bridge_health.broken", { n: counts.fail ?? 0 })}
                        </Badge>
                        {report.stale && (
                            <Badge variant="outline" className="gap-1">
                                <AlertTriangle className="size-3" />
                                {t("page.bridge_health.stale")}
                            </Badge>
                        )}
                    </div>

                    {report.apply_blocked && (
                        <Card className="border-destructive">
                            <CardContent className="p-3 text-sm">
                                {t("page.bridge_health.apply_blocked")}
                            </CardContent>
                        </Card>
                    )}

                    {report.scan_running && log.length > 0 && (
                        <Card>
                            <CardContent className="p-3">
                                <pre className="text-xs overflow-x-auto max-h-52 whitespace-pre-wrap">
                                    {log.join("\n")}
                                </pre>
                            </CardContent>
                        </Card>
                    )}

                    <BridgeMatrix matrix={report.matrix ?? {}} />
                    <MatrixLegend />
                    <BridgeHostLists
                        hosts={report.hosts ?? []}
                        gaps={report.gaps ?? []}
                        shadowed={report.shadowed ?? []}
                        busy={busy}
                        onApply={apply}
                    />
                </div>
            )}
        </Page>
    );
};

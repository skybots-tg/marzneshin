import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    Button,
    Progress,
} from "@marzneshin/common/components";
import { type FC, useRef, useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { streamSSE, type DonorNode, type NodeRef } from "./api";

interface Props {
    open: boolean;
    onOpenChange: (o: boolean) => void;
    donors: DonorNode[];
    candidates: NodeRef[];
    onDone?: () => void;
}

interface StepRow {
    name: string;
    ok: boolean;
    detail: Record<string, unknown>;
}

const selectClass =
    "w-full px-3 py-2 border rounded-md bg-background text-foreground";

export const PromoteDialog: FC<Props> = ({
    open,
    onOpenChange,
    donors,
    candidates,
    onDone,
}) => {
    const { t } = useTranslation();
    const [donorId, setDonorId] = useState<number | "">("");
    const [targetId, setTargetId] = useState<number | "">("");
    const [regenKeys, setRegenKeys] = useState(true);
    const [cloneHosts, setCloneHosts] = useState(true);
    const [running, setRunning] = useState(false);
    const [done, setDone] = useState(false);
    const [success, setSuccess] = useState(false);
    const [steps, setSteps] = useState<StepRow[]>([]);
    const [logs, setLogs] = useState<string[]>([]);
    const abortRef = useRef<AbortController | null>(null);
    const logEnd = useRef<HTMLDivElement>(null);

    useEffect(() => {
        logEnd.current?.scrollIntoView({ behavior: "smooth" });
    }, [logs, steps]);

    const start = () => {
        if (donorId === "" || targetId === "" || donorId === targetId) return;
        setRunning(true);
        setDone(false);
        setSteps([]);
        setLogs([]);
        const ac = new AbortController();
        abortRef.current = ac;
        streamSSE(
            "/api/topology/promote-universal",
            {
                donor_node_id: Number(donorId),
                target_node_id: Number(targetId),
                regenerate_reality_keys: regenKeys,
                clone_hosts: cloneHosts,
            },
            {
                onLog: (m) => setLogs((p) => [...p, m]),
                onStep: (s) => setSteps((p) => [...p, s]),
                onError: (m) => setLogs((p) => [...p, `ERROR: ${m}`]),
                onComplete: (ok, failed) => {
                    setRunning(false);
                    setDone(true);
                    setSuccess(ok);
                    setLogs((p) => [
                        ...p,
                        ok
                            ? t("page.topology.promote.success")
                            : `${t("page.topology.promote.failed")}${failed ? ` (${failed})` : ""}`,
                    ]);
                    onDone?.();
                },
            },
            ac.signal,
        ).catch((e) => {
            if (e?.name !== "AbortError") {
                setRunning(false);
                setDone(true);
                setSuccess(false);
            }
        });
    };

    const close = () => {
        abortRef.current?.abort();
        onOpenChange(false);
    };

    const progress =
        steps.length === 0 ? (running ? 5 : 0) : Math.min(100, steps.length * 14);

    return (
        <Dialog open={open} onOpenChange={close}>
            <DialogContent className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle>{t("page.topology.promote.title")}</DialogTitle>
                    <DialogDescription>
                        {t("page.topology.promote.description")}
                    </DialogDescription>
                </DialogHeader>

                {!running && !done && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.topology.promote.donor")}
                            </label>
                            <select
                                className={selectClass}
                                value={donorId}
                                onChange={(e) =>
                                    setDonorId(e.target.value ? Number(e.target.value) : "")
                                }
                            >
                                <option value="">—</option>
                                {donors.map((d) => (
                                    <option key={d.node_id} value={d.node_id}>
                                        {d.name} ({d.key.toUpperCase()}, {d.exit_count} exits)
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.topology.promote.target")}
                            </label>
                            <select
                                className={selectClass}
                                value={targetId}
                                onChange={(e) =>
                                    setTargetId(e.target.value ? Number(e.target.value) : "")
                                }
                            >
                                <option value="">—</option>
                                {candidates.map((c) => (
                                    <option key={c.node_id} value={c.node_id}>
                                        {c.name} ({c.address})
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="flex gap-4 flex-wrap">
                            <label className="flex items-center gap-2 text-sm">
                                <input
                                    type="checkbox"
                                    checked={regenKeys}
                                    onChange={(e) => setRegenKeys(e.target.checked)}
                                />
                                {t("page.topology.promote.regen_keys")}
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                                <input
                                    type="checkbox"
                                    checked={cloneHosts}
                                    onChange={(e) => setCloneHosts(e.target.checked)}
                                />
                                {t("page.topology.promote.clone_hosts")}
                            </label>
                        </div>
                        {donorId !== "" && donorId === targetId && (
                            <p className="text-sm text-red-500">
                                {t("page.topology.promote.same_node")}
                            </p>
                        )}
                        <Button
                            className="w-full"
                            onClick={start}
                            disabled={donorId === "" || targetId === "" || donorId === targetId}
                        >
                            {t("page.topology.promote.start")}
                        </Button>
                    </div>
                )}

                {(running || done) && (
                    <div className="space-y-4">
                        <Progress value={progress} className="w-full" />
                        {steps.length > 0 && (
                            <div className="space-y-2 max-h-44 overflow-y-auto border rounded-md p-3">
                                {steps.map((s, i) => (
                                    <div key={i} className="flex items-center gap-2 text-sm">
                                        {s.ok ? (
                                            <CheckCircle2 className="size-4 text-green-500" />
                                        ) : (
                                            <XCircle className="size-4 text-red-500" />
                                        )}
                                        <span>{s.name}</span>
                                    </div>
                                ))}
                                {running && (
                                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                        <Loader2 className="size-4 animate-spin" />
                                        {t("page.topology.promote.working")}
                                    </div>
                                )}
                            </div>
                        )}
                        <div className="bg-black text-green-400 p-3 rounded-md font-mono text-xs max-h-60 overflow-y-auto">
                            {logs.map((l, i) => (
                                <div key={i}>{l}</div>
                            ))}
                            <div ref={logEnd} />
                        </div>
                        {done && (
                            <div className="flex items-center gap-2">
                                {success ? (
                                    <CheckCircle2 className="size-5 text-green-500" />
                                ) : (
                                    <XCircle className="size-5 text-red-500" />
                                )}
                                <Button variant="outline" className="flex-1" onClick={close}>
                                    {t("close")}
                                </Button>
                            </div>
                        )}
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
};

import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    Button,
    Badge,
} from "@marzneshin/common/components";
import { type FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { planExitCountry, type ExitPlan, type NodeRef } from "./api";

interface Props {
    open: boolean;
    onOpenChange: (o: boolean) => void;
    nodes: NodeRef[];
}

const fieldClass =
    "w-full px-3 py-2 border rounded-md bg-background text-foreground";

export const PlanExitDialog: FC<Props> = ({ open, onOpenChange, nodes }) => {
    const { t } = useTranslation();
    const [exitId, setExitId] = useState<number | "">("");
    const [iso, setIso] = useState("");
    const [label, setLabel] = useState("");
    const [universal, setUniversal] = useState(true);
    const [elite, setElite] = useState(true);
    const [loading, setLoading] = useState(false);
    const [plan, setPlan] = useState<ExitPlan | null>(null);

    const compute = async () => {
        if (exitId === "") return;
        setLoading(true);
        setPlan(null);
        try {
            const p = await planExitCountry({
                exit_node_id: Number(exitId),
                flag_iso: iso.trim(),
                label: label.trim() || iso.trim(),
                include_universal: universal,
                include_elite: elite,
            });
            setPlan(p);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle>{t("page.topology.exit.title")}</DialogTitle>
                    <DialogDescription>
                        {t("page.topology.exit.description")}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div className="space-y-1 sm:col-span-3">
                            <label className="text-sm font-medium">
                                {t("page.topology.exit.exit_node")}
                            </label>
                            <select
                                className={fieldClass}
                                value={exitId}
                                onChange={(e) =>
                                    setExitId(e.target.value ? Number(e.target.value) : "")
                                }
                            >
                                <option value="">—</option>
                                {nodes.map((n) => (
                                    <option key={n.node_id} value={n.node_id}>
                                        {n.name} {n.address ? `(${n.address})` : ""}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="space-y-1">
                            <label className="text-sm font-medium">
                                {t("page.topology.exit.iso")}
                            </label>
                            <input
                                className={fieldClass}
                                placeholder="RO"
                                maxLength={2}
                                value={iso}
                                onChange={(e) => setIso(e.target.value.toUpperCase())}
                            />
                        </div>
                        <div className="space-y-1 sm:col-span-2">
                            <label className="text-sm font-medium">
                                {t("page.topology.exit.label")}
                            </label>
                            <input
                                className={fieldClass}
                                placeholder="RO"
                                value={label}
                                onChange={(e) => setLabel(e.target.value)}
                            />
                        </div>
                    </div>
                    <div className="flex gap-4">
                        <label className="flex items-center gap-2 text-sm">
                            <input
                                type="checkbox"
                                checked={universal}
                                onChange={(e) => setUniversal(e.target.checked)}
                            />
                            {t("page.topology.exit.universal")}
                        </label>
                        <label className="flex items-center gap-2 text-sm">
                            <input
                                type="checkbox"
                                checked={elite}
                                onChange={(e) => setElite(e.target.checked)}
                            />
                            {t("page.topology.exit.elite")}
                        </label>
                    </div>
                    <Button onClick={compute} disabled={exitId === "" || loading}>
                        {loading && <Loader2 className="size-4 animate-spin mr-2" />}
                        {t("page.topology.exit.compute")}
                    </Button>

                    {plan && !plan.error && (
                        <div className="space-y-3 border rounded-md p-3 text-sm">
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-medium">{plan.exit_node.name}</span>
                                <Badge variant="secondary">{plan.iso || "?"}</Badge>
                                <Badge variant={plan.grpc_reachable ? "default" : "destructive"}>
                                    {plan.grpc_reachable
                                        ? t("page.topology.exit.grpc_ok")
                                        : t("page.topology.exit.grpc_down")}
                                </Badge>
                            </div>
                            <div>
                                {t("page.topology.exit.listeners")}:{" "}
                                {plan.reality_listeners.length === 0 ? (
                                    <span className="text-amber-500 inline-flex items-center gap-1">
                                        <AlertTriangle className="size-4" />
                                        {t("page.topology.exit.no_listener")}
                                    </span>
                                ) : (
                                    plan.reality_listeners
                                        .map((l) => `${l.tag} :${l.port}`)
                                        .join(", ")
                                )}
                            </div>
                            <div>
                                {t("page.topology.exit.pending")} ({plan.pending.length}/
                                {plan.targets_total}):{" "}
                                {plan.pending.length === 0 ? (
                                    <span className="text-green-500 inline-flex items-center gap-1">
                                        <CheckCircle2 className="size-4" />
                                        {t("page.topology.exit.all_have")}
                                    </span>
                                ) : (
                                    <span className="flex flex-wrap gap-1 mt-1">
                                        {plan.pending.map((p) => (
                                            <Badge key={p.node_id} variant="outline">
                                                {p.key.toUpperCase()} · {p.name}
                                            </Badge>
                                        ))}
                                    </span>
                                )}
                            </div>
                            <div>
                                <div className="font-medium mb-1">
                                    {t("page.topology.exit.apply_cmd")}
                                </div>
                                <pre className="bg-black text-green-400 p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">
                                    {plan.apply_command}
                                </pre>
                                <p className="text-xs text-muted-foreground mt-1">{plan.note}</p>
                            </div>
                        </div>
                    )}
                    {plan?.error && (
                        <p className="text-sm text-red-500">{plan.error}</p>
                    )}
                </div>
            </DialogContent>
        </Dialog>
    );
};

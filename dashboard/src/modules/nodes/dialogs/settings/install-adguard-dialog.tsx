import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    Button,
    Input,
    Label,
    Progress,
} from "@marzneshin/common/components";
import type { FC } from "react";
import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, XCircle, Loader2, Circle } from "lucide-react";

interface InstallAdGuardDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    nodeId: number;
    nodeName: string;
}

interface InstallStep {
    id: string;
    name: string;
    status: "pending" | "in_progress" | "success" | "error";
}

export const InstallAdGuardDialog: FC<InstallAdGuardDialogProps> = ({
    open,
    onOpenChange,
    nodeId,
    nodeName,
}) => {
    const { t } = useTranslation();
    const [pin, setPin] = useState("");
    const [steps, setSteps] = useState<InstallStep[]>([]);
    const [logs, setLogs] = useState<string[]>([]);
    const [isRunning, setIsRunning] = useState(false);
    const [isComplete, setIsComplete] = useState(false);
    const [success, setSuccess] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const logsEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [logs]);

    const addLog = (message: string) => setLogs((prev) => [...prev, message]);

    const startInstall = () => {
        setIsRunning(true);
        setIsComplete(false);
        setLogs([]);
        setSteps([]);

        const token = localStorage.getItem("token") || "";
        const controller = new AbortController();
        abortRef.current = controller;

        addLog(t("page.nodes.filtering.adguard.connecting"));

        fetch(`/api/nodes/${nodeId}/install-adguard`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ pin }),
            signal: controller.signal,
        })
            .then(async (response) => {
                if (!response.ok || !response.body) {
                    addLog(t("page.nodes.filtering.adguard.connection_failed"));
                    setIsRunning(false);
                    setIsComplete(true);
                    setSuccess(false);
                    return;
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split("\n\n");
                    buffer = parts.pop() || "";
                    for (const part of parts) {
                        let eventType = "message";
                        let eventData = "";
                        for (const line of part.split("\n")) {
                            if (line.startsWith("event: ")) eventType = line.slice(7);
                            else if (line.startsWith("data: ")) eventData = line.slice(6);
                        }
                        if (!eventData) continue;
                        try {
                            const data = JSON.parse(eventData);
                            if (eventType === "steps") setSteps(data.steps);
                            else if (eventType === "step_update") {
                                setSteps((prev) =>
                                    prev.map((s) =>
                                        s.id === data.step.id ? data.step : s,
                                    ),
                                );
                            } else if (eventType === "log") addLog(data.message);
                            else if (eventType === "error")
                                addLog(`ERROR: ${data.message}`);
                            else if (eventType === "complete") {
                                setIsComplete(true);
                                setIsRunning(false);
                                setSuccess(data.success);
                                addLog(
                                    data.success
                                        ? t("page.nodes.filtering.adguard.success")
                                        : t("page.nodes.filtering.adguard.failed"),
                                );
                            }
                        } catch {
                            /* skip malformed events */
                        }
                    }
                }
            })
            .catch((err) => {
                if (err.name !== "AbortError") {
                    addLog(t("page.nodes.filtering.adguard.connection_failed"));
                    setIsRunning(false);
                    setIsComplete(true);
                    setSuccess(false);
                }
            });
    };

    const stopInstall = () => {
        abortRef.current?.abort();
        abortRef.current = null;
        setIsRunning(false);
    };

    const handleClose = () => {
        stopInstall();
        onOpenChange(false);
    };

    const getStepIcon = (status: InstallStep["status"]) => {
        switch (status) {
            case "success":
                return <CheckCircle2 className="size-4 text-green-500" />;
            case "error":
                return <XCircle className="size-4 text-red-500" />;
            case "in_progress":
                return <Loader2 className="size-4 text-blue-500 animate-spin" />;
            case "pending":
                return <Circle className="size-4 text-gray-400" />;
        }
    };

    const getProgress = () => {
        if (steps.length === 0) return 0;
        const done = steps.filter(
            (s) => s.status === "success" || s.status === "error",
        ).length;
        return (done / steps.length) * 100;
    };

    return (
        <Dialog open={open} onOpenChange={handleClose}>
            <DialogContent
                className="max-w-3xl"
                onClick={(e) => e.stopPropagation()}
            >
                <DialogHeader>
                    <DialogTitle>
                        {t("page.nodes.filtering.adguard.install_title")}
                    </DialogTitle>
                    <DialogDescription>
                        {t("page.nodes.filtering.adguard.install_desc", {
                            name: nodeName,
                        })}
                    </DialogDescription>
                </DialogHeader>

                {!isRunning && !isComplete && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <Label>{t("page.nodes.filtering.ssh.pin")}</Label>
                            <Input
                                type="password"
                                maxLength={4}
                                placeholder="****"
                                value={pin}
                                onChange={(e) =>
                                    setPin(
                                        e.target.value.replace(/\D/g, "").slice(0, 4),
                                    )
                                }
                            />
                        </div>
                        <Button
                            onClick={startInstall}
                            className="w-full"
                            disabled={pin.length !== 4}
                        >
                            {t("page.nodes.filtering.adguard.install_btn")}
                        </Button>
                    </div>
                )}

                {(isRunning || isComplete) && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <div className="flex justify-between items-center">
                                <span className="text-sm font-medium">
                                    {t("page.nodes.filtering.adguard.progress")}
                                </span>
                                <span className="text-sm text-muted-foreground">
                                    {Math.round(getProgress())}%
                                </span>
                            </div>
                            <Progress value={getProgress()} className="w-full" />
                        </div>

                        {steps.length > 0 && (
                            <div className="space-y-2 max-h-40 overflow-y-auto border rounded-md p-3">
                                {steps.map((step) => (
                                    <div
                                        key={step.id}
                                        className="flex items-center gap-2 text-sm"
                                    >
                                        {getStepIcon(step.status)}
                                        <span>{step.name}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        <div className="space-y-2">
                            <div className="text-sm font-medium">
                                {t("page.nodes.filtering.adguard.logs")}
                            </div>
                            <div className="bg-black text-green-400 p-3 rounded-md font-mono text-xs max-h-60 overflow-y-auto">
                                {logs.map((log, index) => (
                                    <div key={index}>{log}</div>
                                ))}
                                <div ref={logsEndRef} />
                            </div>
                        </div>

                        {isComplete && (
                            <div className="flex gap-2">
                                <Button
                                    onClick={handleClose}
                                    variant="outline"
                                    className="flex-1"
                                >
                                    {t("close")}
                                </Button>
                                {!success && (
                                    <Button
                                        onClick={() => {
                                            setIsComplete(false);
                                            startInstall();
                                        }}
                                        className="flex-1"
                                    >
                                        {t("page.nodes.filtering.adguard.retry")}
                                    </Button>
                                )}
                            </div>
                        )}

                        {isRunning && (
                            <Button
                                onClick={stopInstall}
                                variant="destructive"
                                className="w-full"
                            >
                                {t("page.nodes.filtering.adguard.stop")}
                            </Button>
                        )}
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
};

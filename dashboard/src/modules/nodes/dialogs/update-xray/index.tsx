import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    Button,
    Progress,
} from "@marzneshin/common/components";
import type { FC } from "react";
import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { NodeType } from "@marzneshin/modules/nodes";
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { 
    faCheckCircle, 
    faTimesCircle, 
    faSpinner,
    faCircle 
} from '@fortawesome/free-solid-svg-icons';

interface UpdateXrayDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    node: NodeType;
}

interface UpdateStep {
    id: string;
    name: string;
    status: "pending" | "in_progress" | "success" | "error";
}

export const UpdateXrayDialog: FC<UpdateXrayDialogProps> = ({
    open,
    onOpenChange,
    node,
}) => {
    const { t } = useTranslation();
    const [steps, setSteps] = useState<UpdateStep[]>([]);
    const [logs, setLogs] = useState<string[]>([]);
    const [isRunning, setIsRunning] = useState(false);
    const [isComplete, setIsComplete] = useState(false);
    const [success, setSuccess] = useState(false);
    const [sshConfig, setSshConfig] = useState({
        user: "root",
        port: "22",
        key: "",
        password: "",
        authMethod: "password" as "password" | "key",
    });
    const eventSourceRef = useRef<EventSource | null>(null);
    const logsEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [logs]);

    const startUpdate = () => {
        setIsRunning(true);
        setIsComplete(false);
        setLogs([]);
        setSteps([]);

        const token = localStorage.getItem("token") || "";
        const abortController = new AbortController();
        eventSourceRef.current = { close: () => abortController.abort() } as EventSource;

        addLog(t("page.nodes.update_xray.connected"));

        const body: Record<string, string | number> = {
            ssh_user: sshConfig.user,
            ssh_port: Number(sshConfig.port),
        };
        if (sshConfig.authMethod === "key" && sshConfig.key) {
            body.ssh_key = sshConfig.key;
        } else if (sshConfig.authMethod === "password" && sshConfig.password) {
            body.ssh_password = sshConfig.password;
        }

        fetch(`/api/nodes/${node.id}/update-xray`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`,
            },
            body: JSON.stringify(body),
            signal: abortController.signal,
        })
            .then(async (response) => {
                if (!response.ok || !response.body) {
                    addLog(t("page.nodes.update_xray.disconnected"));
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
                                    prev.map((s) => (s.id === data.step.id ? data.step : s))
                                );
                            } else if (eventType === "log") addLog(data.message);
                            else if (eventType === "error") addLog(`ERROR: ${data.message}`);
                            else if (eventType === "complete") {
                                setIsComplete(true);
                                setIsRunning(false);
                                setSuccess(data.success);
                                addLog(
                                    data.success
                                        ? t("page.nodes.update_xray.success")
                                        : t("page.nodes.update_xray.failed")
                                );
                            }
                        } catch (e) {
                            console.error("Failed to parse SSE event:", e);
                        }
                    }
                }
            })
            .catch((err) => {
                if (err.name !== "AbortError") {
                    console.error("Fetch SSE error:", err);
                    addLog(t("page.nodes.update_xray.disconnected"));
                    setIsRunning(false);
                    setIsComplete(true);
                    setSuccess(false);
                }
            });
    };

    const addLog = (message: string) => {
        setLogs((prev) => [...prev, message]);
    };

    const stopUpdate = () => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }
        setIsRunning(false);
    };

    const handleClose = () => {
        stopUpdate();
        onOpenChange(false);
    };

    const getStepIcon = (status: UpdateStep["status"]) => {
        switch (status) {
            case "success":
                return <FontAwesomeIcon icon={faCheckCircle} className="text-green-500" />;
            case "error":
                return <FontAwesomeIcon icon={faTimesCircle} className="text-red-500" />;
            case "in_progress":
                return <FontAwesomeIcon icon={faSpinner} className="text-blue-500 animate-spin" />;
            case "pending":
                return <FontAwesomeIcon icon={faCircle} className="text-gray-400" />;
        }
    };

    const getProgress = () => {
        if (steps.length === 0) return 0;
        const completed = steps.filter(
            (s) => s.status === "success" || s.status === "error"
        ).length;
        return (completed / steps.length) * 100;
    };

    // Get current xray version from node backends
    const currentXrayVersion = node.backends?.find(b => b.backend_type === "xray")?.version || "unknown";

    return (
        <Dialog open={open} onOpenChange={handleClose}>
            <DialogContent 
                className="max-w-3xl"
                onClick={(e) => e.stopPropagation()}
            >
                <DialogHeader>
                    <DialogTitle>{t("page.nodes.update_xray.title")}</DialogTitle>
                    <DialogDescription>
                        {t("page.nodes.update_xray.description", { name: node.name, version: currentXrayVersion })}
                    </DialogDescription>
                </DialogHeader>

                {!isRunning && !isComplete && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.nodes.update_xray.ssh_user")}
                            </label>
                            <input
                                type="text"
                                className="w-full px-3 py-2 border rounded-md bg-background text-foreground"
                                value={sshConfig.user}
                                onChange={(e) =>
                                    setSshConfig({ ...sshConfig, user: e.target.value })
                                }
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.nodes.update_xray.ssh_port")}
                            </label>
                            <input
                                type="text"
                                className="w-full px-3 py-2 border rounded-md bg-background text-foreground"
                                value={sshConfig.port}
                                onChange={(e) =>
                                    setSshConfig({ ...sshConfig, port: e.target.value })
                                }
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.nodes.update_xray.auth_method")}
                            </label>
                            <div className="flex gap-4">
                                <label className="flex items-center gap-2">
                                    <input
                                        type="radio"
                                        name="updateXrayAuthMethod"
                                        value="password"
                                        checked={sshConfig.authMethod === "password"}
                                        onChange={() =>
                                            setSshConfig({ ...sshConfig, authMethod: "password" })
                                        }
                                    />
                                    <span className="text-sm">{t("page.nodes.update_xray.password")}</span>
                                </label>
                                <label className="flex items-center gap-2">
                                    <input
                                        type="radio"
                                        name="updateXrayAuthMethod"
                                        value="key"
                                        checked={sshConfig.authMethod === "key"}
                                        onChange={() =>
                                            setSshConfig({ ...sshConfig, authMethod: "key" })
                                        }
                                    />
                                    <span className="text-sm">{t("page.nodes.update_xray.ssh_key_auth")}</span>
                                </label>
                            </div>
                        </div>

                        {sshConfig.authMethod === "password" ? (
                            <div className="space-y-2">
                                <label className="text-sm font-medium">
                                    {t("page.nodes.update_xray.ssh_password")}
                                </label>
                                <input
                                    type="password"
                                    className="w-full px-3 py-2 border rounded-md bg-background text-foreground"
                                    value={sshConfig.password}
                                    onChange={(e) =>
                                        setSshConfig({ ...sshConfig, password: e.target.value })
                                    }
                                />
                            </div>
                        ) : (
                            <div className="space-y-2">
                                <label className="text-sm font-medium">
                                    {t("page.nodes.update_xray.ssh_key")}
                                </label>
                                <input
                                    type="text"
                                    placeholder="/path/to/ssh/key"
                                    className="w-full px-3 py-2 border rounded-md bg-background text-foreground"
                                    value={sshConfig.key}
                                    onChange={(e) =>
                                        setSshConfig({ ...sshConfig, key: e.target.value })
                                    }
                                />
                            </div>
                        )}

                        <Button
                            onClick={startUpdate}
                            className="w-full"
                        >
                            {t("page.nodes.update_xray.start")}
                        </Button>
                    </div>
                )}

                {(isRunning || isComplete) && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <div className="flex justify-between items-center">
                                <span className="text-sm font-medium">
                                    {t("page.nodes.update_xray.progress")}
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
                                {t("page.nodes.update_xray.logs")}
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
                                            startUpdate();
                                        }}
                                        className="flex-1"
                                    >
                                        {t("page.nodes.update_xray.retry")}
                                    </Button>
                                )}
                            </div>
                        )}

                        {isRunning && (
                            <Button
                                onClick={stopUpdate}
                                variant="destructive"
                                className="w-full"
                            >
                                {t("page.nodes.update_xray.stop")}
                            </Button>
                        )}
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
};

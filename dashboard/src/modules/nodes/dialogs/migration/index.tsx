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

interface MigrationDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    node: NodeType;
}

interface MigrationStep {
    id: string;
    name: string;
    status: "pending" | "in_progress" | "success" | "error";
}

export const MigrationDialog: FC<MigrationDialogProps> = ({
    open,
    onOpenChange,
    node,
}) => {
    const { t } = useTranslation();
    const [steps, setSteps] = useState<MigrationStep[]>([]);
    const [logs, setLogs] = useState<string[]>([]);
    const [isRunning, setIsRunning] = useState(false);
    const [isComplete, setIsComplete] = useState(false);
    const [success, setSuccess] = useState(false);
    const [sshConfig, setSshConfig] = useState({
        user: "root",
        port: "22",
        key: "",
    });
    const wsRef = useRef<WebSocket | null>(null);
    const logsEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [logs]);

    const startMigration = () => {
        setIsRunning(true);
        setIsComplete(false);
        setLogs([]);
        setSteps([]);

        const token = localStorage.getItem("token") || "";
        const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${wsProtocol}//${window.location.host}/api/nodes/${node.id}/migrate?token=${token}&ssh_user=${sshConfig.user}&ssh_port=${sshConfig.port}&ssh_key=${encodeURIComponent(sshConfig.key)}`;

        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            addLog(t("page.nodes.migration.connected"));
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                switch (data.type) {
                    case "steps":
                        setSteps(data.steps);
                        break;

                    case "step_update":
                        setSteps((prevSteps) =>
                            prevSteps.map((step) =>
                                step.id === data.step.id ? data.step : step
                            )
                        );
                        break;

                    case "log":
                        addLog(data.message);
                        break;

                    case "complete":
                        setIsComplete(true);
                        setIsRunning(false);
                        setSuccess(data.success);
                        addLog(
                            data.success
                                ? t("page.nodes.migration.success")
                                : t("page.nodes.migration.failed")
                        );
                        break;

                    case "error":
                        addLog(`ERROR: ${data.message}`);
                        setIsRunning(false);
                        setIsComplete(true);
                        setSuccess(false);
                        break;
                }
            } catch (error) {
                console.error("Failed to parse WebSocket message:", error);
            }
        };

        ws.onerror = (error) => {
            addLog(`WebSocket error: ${error}`);
            setIsRunning(false);
            setIsComplete(true);
            setSuccess(false);
        };

        ws.onclose = () => {
            addLog(t("page.nodes.migration.disconnected"));
            if (isRunning) {
                setIsRunning(false);
                setIsComplete(true);
            }
        };
    };

    const addLog = (message: string) => {
        setLogs((prev) => [...prev, message]);
    };

    const stopMigration = () => {
        if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
        }
        setIsRunning(false);
    };

    const handleClose = () => {
        stopMigration();
        onOpenChange(false);
    };

    const getStepIcon = (status: MigrationStep["status"]) => {
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

    return (
        <Dialog open={open} onOpenChange={handleClose}>
            <DialogContent className="max-w-3xl max-h-[90vh]">
                <DialogHeader>
                    <DialogTitle>{t("page.nodes.migration.title")}</DialogTitle>
                    <DialogDescription>
                        {t("page.nodes.migration.description", { name: node.name })}
                    </DialogDescription>
                </DialogHeader>

                {!isRunning && !isComplete && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.nodes.migration.ssh_user")}
                            </label>
                            <input
                                type="text"
                                className="w-full px-3 py-2 border rounded-md"
                                value={sshConfig.user}
                                onChange={(e) =>
                                    setSshConfig({ ...sshConfig, user: e.target.value })
                                }
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.nodes.migration.ssh_port")}
                            </label>
                            <input
                                type="text"
                                className="w-full px-3 py-2 border rounded-md"
                                value={sshConfig.port}
                                onChange={(e) =>
                                    setSshConfig({ ...sshConfig, port: e.target.value })
                                }
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.nodes.migration.ssh_key")}
                            </label>
                            <input
                                type="text"
                                placeholder="/path/to/ssh/key (optional)"
                                className="w-full px-3 py-2 border rounded-md"
                                value={sshConfig.key}
                                onChange={(e) =>
                                    setSshConfig({ ...sshConfig, key: e.target.value })
                                }
                            />
                        </div>

                        <Button
                            onClick={startMigration}
                            className="w-full"
                        >
                            {t("page.nodes.migration.start")}
                        </Button>
                    </div>
                )}

                {(isRunning || isComplete) && (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <div className="flex justify-between items-center">
                                <span className="text-sm font-medium">
                                    {t("page.nodes.migration.progress")}
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
                                {t("page.nodes.migration.logs")}
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
                                            startMigration();
                                        }}
                                        className="flex-1"
                                    >
                                        {t("page.nodes.migration.retry")}
                                    </Button>
                                )}
                            </div>
                        )}

                        {isRunning && (
                            <Button
                                onClick={stopMigration}
                                variant="destructive"
                                className="w-full"
                            >
                                {t("page.nodes.migration.stop")}
                            </Button>
                        )}
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
};

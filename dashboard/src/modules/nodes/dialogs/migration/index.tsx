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

    const startMigration = () => {
        setIsRunning(true);
        setIsComplete(false);
        setLogs([]);
        setSteps([]);

        const token = localStorage.getItem("token") || "";
        
        // Build HTTP URL for Server-Sent Events (not WebSocket)
        let url = `/api/nodes/${node.id}/migrate?token=${token}&ssh_user=${encodeURIComponent(sshConfig.user)}&ssh_port=${encodeURIComponent(sshConfig.port)}`;
        
        if (sshConfig.authMethod === "key" && sshConfig.key) {
            url += `&ssh_key=${encodeURIComponent(sshConfig.key)}`;
        } else if (sshConfig.authMethod === "password" && sshConfig.password) {
            url += `&ssh_password=${encodeURIComponent(sshConfig.password)}`;
        }

        // Use EventSource for Server-Sent Events  
        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        addLog(t("page.nodes.migration.connected"));

        // Handle different event types
        eventSource.addEventListener("steps", (event) => {
            try {
                const data = JSON.parse(event.data);
                setSteps(data.steps);
            } catch (error) {
                console.error("Failed to parse steps event:", error);
            }
        });

        eventSource.addEventListener("step_update", (event) => {
            try {
                const data = JSON.parse(event.data);
                setSteps((prevSteps) =>
                    prevSteps.map((step) =>
                        step.id === data.step.id ? data.step : step
                    )
                );
            } catch (error) {
                console.error("Failed to parse step_update event:", error);
            }
        });

        eventSource.addEventListener("log", (event) => {
            try {
                const data = JSON.parse(event.data);
                addLog(data.message);
            } catch (error) {
                console.error("Failed to parse log event:", error);
            }
        });

        eventSource.addEventListener("complete", (event) => {
            try {
                const data = JSON.parse(event.data);
                setIsComplete(true);
                setIsRunning(false);
                setSuccess(data.success);
                addLog(
                    data.success
                        ? t("page.nodes.migration.success")
                        : t("page.nodes.migration.failed")
                );
                eventSource.close();
            } catch (error) {
                console.error("Failed to parse complete event:", error);
            }
        });

        eventSource.addEventListener("error", (event) => {
            try {
                const data = JSON.parse((event as MessageEvent).data);
                addLog(`ERROR: ${data.message}`);
            } catch (error) {
                // If parsing fails, it's a connection error
                console.error("EventSource connection error:", error);
            }
        });

        // Handle connection errors
        eventSource.onerror = (error) => {
            console.error("EventSource error:", error);
            addLog(t("page.nodes.migration.disconnected"));
            if (isRunning) {
                setIsRunning(false);
                setIsComplete(true);
                setSuccess(false);
            }
            eventSource.close();
        };
    };

    const addLog = (message: string) => {
        setLogs((prev) => [...prev, message]);
    };

    const stopMigration = () => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
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
            <DialogContent 
                className="max-w-3xl max-h-[90vh]"
                onClick={(e) => e.stopPropagation()}
            >
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
                                className="w-full px-3 py-2 border rounded-md bg-background text-foreground"
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
                                className="w-full px-3 py-2 border rounded-md bg-background text-foreground"
                                value={sshConfig.port}
                                onChange={(e) =>
                                    setSshConfig({ ...sshConfig, port: e.target.value })
                                }
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">
                                {t("page.nodes.migration.auth_method")}
                            </label>
                            <div className="flex gap-4">
                                <label className="flex items-center gap-2">
                                    <input
                                        type="radio"
                                        name="authMethod"
                                        value="password"
                                        checked={sshConfig.authMethod === "password"}
                                        onChange={() =>
                                            setSshConfig({ ...sshConfig, authMethod: "password" })
                                        }
                                    />
                                    <span className="text-sm">{t("page.nodes.migration.password")}</span>
                                </label>
                                <label className="flex items-center gap-2">
                                    <input
                                        type="radio"
                                        name="authMethod"
                                        value="key"
                                        checked={sshConfig.authMethod === "key"}
                                        onChange={() =>
                                            setSshConfig({ ...sshConfig, authMethod: "key" })
                                        }
                                    />
                                    <span className="text-sm">{t("page.nodes.migration.ssh_key_auth")}</span>
                                </label>
                            </div>
                        </div>

                        {sshConfig.authMethod === "password" ? (
                            <div className="space-y-2">
                                <label className="text-sm font-medium">
                                    {t("page.nodes.migration.ssh_password")}
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
                                    {t("page.nodes.migration.ssh_key")}
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

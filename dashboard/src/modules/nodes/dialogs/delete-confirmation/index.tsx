import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Progress,
} from "@marzneshin/common/components";
import { ExclamationTriangleIcon } from "@radix-ui/react-icons";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { FC } from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { queryClient } from "@marzneshin/common/utils";
import { NodesQueryFetchKey, type NodeType } from "@marzneshin/modules/nodes";

type StepStatus = "pending" | "in_progress" | "success" | "error";

interface DeletionStep {
    id: string;
    status: StepStatus;
    done: number;
    total: number;
}

interface NodesDeleteConfirmationDialogProps {
    onOpenChange: (state: boolean) => void;
    open: boolean;
    entity: NodeType;
    onClose: () => void;
}

const getIcon = (status: StepStatus) => {
    switch (status) {
        case "success":
            return <CheckCircle2 className="size-4 text-green-500 shrink-0" />;
        case "error":
            return <XCircle className="size-4 text-red-500 shrink-0" />;
        case "in_progress":
            return <Loader2 className="size-4 text-blue-500 animate-spin shrink-0" />;
        default:
            return <Circle className="size-4 text-gray-400 shrink-0" />;
    }
};

const formatCount = (done: number, total: number) => {
    if (total <= 0 && done <= 0) return "";
    if (total <= 0) return `${done}`;
    return `${done.toLocaleString()} / ${total.toLocaleString()}`;
};

export const NodesDeleteConfirmationDialog: FC<NodesDeleteConfirmationDialogProps> = ({
    onOpenChange,
    open,
    entity,
    onClose,
}) => {
    const { t } = useTranslation();
    const abortRef = useRef<AbortController | null>(null);
    const [steps, setSteps] = useState<DeletionStep[]>([]);
    const [isRunning, setIsRunning] = useState(false);
    const [isComplete, setIsComplete] = useState(false);
    const [success, setSuccess] = useState(false);

    useEffect(() => {
        if (!open) {
            abortRef.current?.abort();
            abortRef.current = null;
            setSteps([]);
            setIsRunning(false);
            setIsComplete(false);
            setSuccess(false);
            onClose();
        }
    }, [open, onClose]);

    const handleOpenChange = (next: boolean) => {
        if (!next && isRunning) {
            return;
        }
        onOpenChange(next);
    };

    const updateStep = (patch: Partial<DeletionStep> & { id: string }) => {
        setSteps((prev) =>
            prev.map((step) =>
                step.id === patch.id ? { ...step, ...patch } : step,
            ),
        );
    };

    const startDeletion = async () => {
        setIsRunning(true);
        setIsComplete(false);
        setSuccess(false);
        setSteps([]);

        const token = localStorage.getItem("token") ?? "";
        const controller = new AbortController();
        abortRef.current = controller;

        try {
            const response = await fetch(
                `/api/nodes/${entity.id}/delete-stream`,
                {
                    method: "POST",
                    headers: {
                        Accept: "text/event-stream",
                        Authorization: `Bearer ${token}`,
                    },
                    signal: controller.signal,
                },
            );

            if (!response.ok || !response.body) {
                throw new Error(`HTTP ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let gotComplete = false;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split("\n\n");
                buffer = parts.pop() ?? "";
                for (const part of parts) {
                    let eventType = "message";
                    let eventData = "";
                    for (const line of part.split("\n")) {
                        if (line.startsWith("event: ")) {
                            eventType = line.slice(7);
                        } else if (line.startsWith("data: ")) {
                            eventData = line.slice(6);
                        }
                    }
                    if (!eventData) continue;
                    let payload: any;
                    try {
                        payload = JSON.parse(eventData);
                    } catch {
                        continue;
                    }

                    if (eventType === "steps") {
                        setSteps(
                            (payload.steps ?? []).map((s: any) => ({
                                id: s.id,
                                status: (s.status ?? "pending") as StepStatus,
                                done: s.done ?? 0,
                                total: s.total ?? 0,
                            })),
                        );
                    } else if (eventType === "step_update" && payload.step?.id) {
                        updateStep({
                            id: payload.step.id,
                            status: payload.step.status as StepStatus,
                            done: payload.step.done ?? undefined as any,
                            total: payload.step.total ?? undefined as any,
                        });
                    } else if (eventType === "complete") {
                        gotComplete = true;
                        setSuccess(Boolean(payload.success));
                        setIsComplete(true);
                        setIsRunning(false);
                        if (payload.success) {
                            toast.success(
                                t("page.nodes.deletion.success", { name: entity.name }),
                            );
                            queryClient.invalidateQueries({
                                queryKey: [NodesQueryFetchKey],
                            });
                        } else {
                            toast.error(
                                payload.message ?? t("page.nodes.deletion.failed"),
                            );
                        }
                    } else if (eventType === "error") {
                        toast.error(payload.message ?? t("page.nodes.deletion.failed"));
                    }
                }
            }

            if (!gotComplete) {
                setIsComplete(true);
                setIsRunning(false);
                setSuccess(false);
                toast.error(t("page.nodes.deletion.failed"));
            }
        } catch (err: any) {
            if (err?.name === "AbortError") {
                return;
            }
            setIsRunning(false);
            setIsComplete(true);
            setSuccess(false);
            toast.error(err?.message ?? t("page.nodes.deletion.failed"));
        } finally {
            abortRef.current = null;
        }
    };

    const progress = steps.length
        ? Math.round(
              (steps.filter(
                  (s) => s.status === "success" || s.status === "error",
              ).length /
                  steps.length) *
                  100,
          )
        : 0;

    const stageView = isRunning || isComplete;

    return (
        <AlertDialog open={open} onOpenChange={handleOpenChange}>
            <AlertDialogContent className="max-w-lg">
                <AlertDialogHeader>
                    <AlertDialogTitle className="flex flex-row gap-3 items-center text-destructive">
                        <ExclamationTriangleIcon className="p-2 w-10 h-10 bg-red-200 rounded-md border-2 border-destructive" />
                        {t("page.nodes.deletion.title")}
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                        {stageView
                            ? t("page.nodes.deletion.progress")
                            : t("page.nodes.deletion.description", {
                                  name: entity.name,
                              })}
                    </AlertDialogDescription>
                </AlertDialogHeader>

                {stageView && (
                    <div className="space-y-3">
                        <div className="flex items-center justify-between text-xs text-muted-foreground">
                            <span>{t("page.nodes.deletion.progress")}</span>
                            <span>{progress}%</span>
                        </div>
                        <Progress value={progress} className="w-full" />
                        <div className="border rounded-md divide-y max-h-72 overflow-y-auto">
                            {steps.map((step) => {
                                const pct =
                                    step.total > 0
                                        ? Math.min(
                                              100,
                                              Math.round(
                                                  (step.done / step.total) * 100,
                                              ),
                                          )
                                        : step.status === "success"
                                          ? 100
                                          : 0;
                                return (
                                    <div
                                        key={step.id}
                                        className="flex flex-col gap-1 p-2 text-sm"
                                    >
                                        <div className="flex items-center gap-2">
                                            {getIcon(step.status)}
                                            <span className="flex-1">
                                                {t(
                                                    `page.nodes.deletion.steps.${step.id}`,
                                                )}
                                            </span>
                                            <span className="text-xs text-muted-foreground tabular-nums">
                                                {formatCount(step.done, step.total)}
                                            </span>
                                        </div>
                                        {step.status === "in_progress" &&
                                            step.total > 0 && (
                                                <Progress
                                                    value={pct}
                                                    className="h-1"
                                                />
                                            )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}

                <AlertDialogFooter>
                    {!stageView && (
                        <>
                            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
                            <AlertDialogAction
                                onClick={(e) => {
                                    e.preventDefault();
                                    startDeletion();
                                }}
                                className="bg-destructive"
                            >
                                {t("page.nodes.deletion.start")}
                            </AlertDialogAction>
                        </>
                    )}
                    {stageView && isComplete && (
                        <>
                            {!success && (
                                <Button
                                    variant="outline"
                                    onClick={startDeletion}
                                >
                                    {t("page.nodes.deletion.retry")}
                                </Button>
                            )}
                            <Button onClick={() => onOpenChange(false)}>
                                {t("page.nodes.deletion.close")}
                            </Button>
                        </>
                    )}
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

import { type FC, useEffect, useState, useCallback } from "react";
import {
    Button,
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
    ScrollArea,
    Badge,
} from "@marzneshin/common/components";
import {
    Sortable,
    SortableItem,
    SortableDragHandle,
} from "@marzneshin/common/components/ui/sortable";
import { useTranslation } from "react-i18next";
import { GripVertical, Pencil, Server } from "lucide-react";
import { cn } from "@marzneshin/common/utils";
import { useUpdateHostsWeightsMutation, type HostType } from "@marzneshin/modules/hosts";
import { useNavigate } from "@tanstack/react-router";

interface HostOrderItem {
    id: number;
    remark: string;
    address: string;
    port: number | null;
    weight: number;
    is_disabled: boolean;
}

interface HostsOrderDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    hosts: HostType[];
}

export const HostsOrderDialog: FC<HostsOrderDialogProps> = ({
    open,
    onOpenChange,
    hosts,
}) => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const updateWeightsMutation = useUpdateHostsWeightsMutation();

    const [orderedHosts, setOrderedHosts] = useState<HostOrderItem[]>([]);
    const [hasChanges, setHasChanges] = useState(false);

    // Initialize and sort hosts by weight (descending - higher weight = higher in list)
    useEffect(() => {
        if (hosts && hosts.length > 0) {
            const sortedHosts = [...hosts]
                .filter((h): h is HostType & { id: number } => h.id !== undefined)
                .sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1))
                .map((host) => ({
                    id: host.id,
                    remark: host.remark,
                    address: host.address,
                    port: host.port ?? null,
                    weight: host.weight ?? 1,
                    is_disabled: host.is_disabled ?? false,
                }));
            setOrderedHosts(sortedHosts);
            setHasChanges(false);
        }
    }, [hosts, open]);

    const handleReorder = useCallback((newOrder: HostOrderItem[]) => {
        // Assign new weights based on position (first item gets highest weight)
        const updatedHosts = newOrder.map((host, index) => ({
            ...host,
            weight: newOrder.length - index,
        }));
        setOrderedHosts(updatedHosts);
        setHasChanges(true);
    }, []);

    const handleSave = async () => {
        const weightsToUpdate = orderedHosts.map((host) => ({
            id: host.id,
            weight: host.weight,
        }));

        await updateWeightsMutation.mutateAsync({ hosts: weightsToUpdate });
        onOpenChange(false);
    };

    const handleEditHost = (hostId: number) => {
        onOpenChange(false);
        navigate({
            to: "/hosts/$hostId/edit",
            params: { hostId: String(hostId) },
        });
    };

    const handleClose = () => {
        setHasChanges(false);
        onOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={handleClose}>
            <DialogContent className="max-w-lg">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Server className="h-5 w-5" />
                        {t("page.hosts.order.title")}
                    </DialogTitle>
                    <DialogDescription>
                        {t("page.hosts.order.description")}
                    </DialogDescription>
                </DialogHeader>

                <ScrollArea className="max-h-[60vh] pr-4">
                    {orderedHosts.length === 0 ? (
                        <div className="flex items-center justify-center py-8 text-muted-foreground">
                            {t("page.hosts.order.no-hosts")}
                        </div>
                    ) : (
                        <Sortable
                            value={orderedHosts}
                            onValueChange={handleReorder}
                        >
                            <div className="flex flex-col gap-2">
                                {orderedHosts.map((host, index) => (
                                    <SortableItem
                                        key={host.id}
                                        value={host.id}
                                        asChild
                                    >
                                        <div
                                            className={cn(
                                                "flex items-center gap-3 p-3 rounded-lg border bg-card transition-colors",
                                                host.is_disabled && "opacity-50"
                                            )}
                                        >
                                            <SortableDragHandle
                                                variant="ghost"
                                                size="icon"
                                                className="shrink-0 cursor-grab active:cursor-grabbing"
                                            >
                                                <GripVertical className="h-4 w-4 text-muted-foreground" />
                                            </SortableDragHandle>

                                            <Badge
                                                variant="outline"
                                                className="shrink-0 w-8 justify-center font-mono"
                                            >
                                                {index + 1}
                                            </Badge>

                                            <div className="flex-1 min-w-0">
                                                <div className="font-medium truncate">
                                                    {host.remark}
                                                </div>
                                                <div className="text-sm text-muted-foreground truncate">
                                                    {host.address}
                                                    {host.port && `:${host.port}`}
                                                </div>
                                            </div>

                                            <div className="flex items-center gap-2">
                                                {host.is_disabled && (
                                                    <Badge variant="secondary">
                                                        {t("disabled")}
                                                    </Badge>
                                                )}
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => handleEditHost(host.id)}
                                                    title={t("edit")}
                                                >
                                                    <Pencil className="h-4 w-4" />
                                                </Button>
                                            </div>
                                        </div>
                                    </SortableItem>
                                ))}
                            </div>
                        </Sortable>
                    )}
                </ScrollArea>

                <DialogFooter className="gap-2 sm:gap-0">
                    <Button variant="outline" onClick={handleClose}>
                        {t("cancel")}
                    </Button>
                    <Button
                        onClick={handleSave}
                        disabled={!hasChanges || updateWeightsMutation.isPending}
                    >
                        {updateWeightsMutation.isPending
                            ? t("page.hosts.order.saving")
                            : t("save")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

import { type FC, useEffect, useState, useCallback, useMemo } from "react";
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
import { ChevronDown, ChevronRight, GripVertical, Pencil, Server } from "lucide-react";
import { cn, fetch } from "@marzneshin/common/utils";
import {
    useUpdateHostsWeightsMutation,
    useAllHostsQuery,
    useHostsUpdateMutation,
} from "@marzneshin/modules/hosts";
import { useInboundsQuery } from "@marzneshin/modules/inbounds";
import { useNavigate } from "@tanstack/react-router";

interface HostOrderItem {
    id: number;
    remark: string;
    address: string;
    port: number | null;
    weight: number;
    is_disabled: boolean;
    inbound_id: number | null;
    inbound_tag?: string;
}

interface HostsOrderDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export const HostsOrderDialog: FC<HostsOrderDialogProps> = ({
    open,
    onOpenChange,
}) => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const updateWeightsMutation = useUpdateHostsWeightsMutation();
    const updateHostMutation = useHostsUpdateMutation();

    const { data: allHosts, refetch: refetchHosts } = useAllHostsQuery();
    const { data: inboundsData } = useInboundsQuery({ page: 1, size: 100 });

    const [orderedHosts, setOrderedHosts] = useState<HostOrderItem[]>([]);
    const [hasChanges, setHasChanges] = useState(false);
    const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
    const [editingHostId, setEditingHostId] = useState<number | null>(null);
    const [editingRemark, setEditingRemark] = useState<string>("");

    // Create a map of inbound id to tag
    const inboundMap = useMemo(() => {
        const map = new Map<number, string>();
        inboundsData.entities.forEach((inbound) => {
            if (inbound.id !== undefined) {
                map.set(inbound.id, inbound.tag);
            }
        });
        return map;
    }, [inboundsData.entities]);

    // Initialize and sort hosts by weight (ascending - lower weight = higher in list)
    useEffect(() => {
        if (open) {
            refetchHosts();
        }
    }, [open, refetchHosts]);

    useEffect(() => {
        if (allHosts && allHosts.length > 0) {
            const sortedHosts = [...allHosts]
                .sort((a, b) => (a.weight ?? 1) - (b.weight ?? 1))
                .map((host) => ({
                    id: host.id,
                    remark: host.remark,
                    address: host.address,
                    port: host.port ?? null,
                    weight: host.weight ?? 1,
                    is_disabled: host.is_disabled ?? false,
                    inbound_id: host.inbound_id,
                    inbound_tag: host.inbound_id
                        ? inboundMap.get(host.inbound_id) ?? `Inbound #${host.inbound_id}`
                        : "Universal",
                }));
            setOrderedHosts(sortedHosts);
            setHasChanges(false);
            setCollapsedGroups({});
            setEditingHostId(null);
            setEditingRemark("");
        }
    }, [allHosts, inboundMap]);

    const getGroupKey = (host: HostOrderItem) =>
        host.inbound_id !== null && host.inbound_id !== undefined
            ? String(host.inbound_id)
            : "universal";

    const handleGroupReorder = useCallback((groupKey: string, newGroupOrder: HostOrderItem[]) => {
        setOrderedHosts((prev) => {
            // Build groups from previous state
            const groups = new Map<string, HostOrderItem[]>();
            prev.forEach((host) => {
                const key = getGroupKey(host);
                const list = groups.get(key) ?? [];
                list.push(host);
                groups.set(key, list);
            });

            // Replace the reordered group
            groups.set(groupKey, newGroupOrder);

            // Determine a stable order of groups
            const sortedGroupKeys = Array.from(groups.keys()).sort((a, b) => {
                const groupA = groups.get(a)?.[0];
                const groupB = groups.get(b)?.[0];
                const inboundIdA = groupA?.inbound_id ?? null;
                const inboundIdB = groupB?.inbound_id ?? null;
                const labelA =
                    groupA?.inbound_tag ??
                    (inboundIdA ? `Inbound #${inboundIdA}` : t("page.hosts.order.universal", "Universal"));
                const labelB =
                    groupB?.inbound_tag ??
                    (inboundIdB ? `Inbound #${inboundIdB}` : t("page.hosts.order.universal", "Universal"));

                if (inboundIdA === null && inboundIdB !== null) return -1;
                if (inboundIdA !== null && inboundIdB === null) return 1;
                return labelA.localeCompare(labelB);
            });

            const flattened: HostOrderItem[] = [];
            sortedGroupKeys.forEach((key) => {
                const hosts = groups.get(key);
                if (hosts) {
                    flattened.push(...hosts);
                }
            });

            const updatedHosts = flattened.map((host, index) => ({
                ...host,
                weight: index + 1,
            }));

            return updatedHosts;
        });
        setHasChanges(true);
    }, [t]);

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

    const toggleGroup = (groupKey: string) => {
        setCollapsedGroups((prev) => ({
            ...prev,
            [groupKey]: !prev[groupKey],
        }));
    };

    const { groupedHosts, positionById } = useMemo(() => {
        const groups = new Map<
            string,
            { inboundId: number | null; label: string; hosts: HostOrderItem[] }
        >();
        const positions = new Map<number, number>();

        orderedHosts.forEach((host, index) => {
            const key = getGroupKey(host);
            const label =
                host.inbound_tag ??
                (host.inbound_id
                    ? inboundMap.get(host.inbound_id) ?? `Inbound #${host.inbound_id}`
                    : t("page.hosts.order.universal", "Universal"));

            const existing = groups.get(key);
            if (existing) {
                existing.hosts.push(host);
            } else {
                groups.set(key, {
                    inboundId: host.inbound_id ?? null,
                    label,
                    hosts: [host],
                });
            }

            positions.set(host.id, index);
        });

        const sortedGroups = Array.from(groups.entries()).sort((a, b) => {
            const groupA = a[1];
            const groupB = b[1];
            const inboundIdA = groupA.inboundId;
            const inboundIdB = groupB.inboundId;

            if (inboundIdA === null && inboundIdB !== null) return -1;
            if (inboundIdA !== null && inboundIdB === null) return 1;
            return groupA.label.localeCompare(groupB.label);
        });

        return { groupedHosts: sortedGroups, positionById: positions };
    }, [orderedHosts, inboundMap, t]);

    const startEditingRemark = (host: HostOrderItem) => {
        setEditingHostId(host.id);
        setEditingRemark(host.remark);
    };

    const cancelEditingRemark = () => {
        setEditingHostId(null);
        setEditingRemark("");
    };

    const saveEditingRemark = async (host: HostOrderItem) => {
        const trimmed = editingRemark.trim();
        if (!trimmed || trimmed === host.remark) {
            cancelEditingRemark();
            return;
        }

        // Load full host payload from backend to avoid losing advanced fields,
        // then update only the remark.
        const fullHost = await fetch(`/inbounds/hosts/${host.id}`);

        await updateHostMutation.mutateAsync({
            hostId: host.id,
            host: {
                ...(fullHost as any),
                remark: trimmed,
            } as any,
        });

        setOrderedHosts((prev) =>
            prev.map((h) => (h.id === host.id ? { ...h, remark: trimmed } : h)),
        );
        cancelEditingRemark();
    };

    const handleClose = () => {
        setHasChanges(false);
        setCollapsedGroups({});
        cancelEditingRemark();
        onOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={handleClose}>
            <DialogContent className="max-w-2xl max-h-[90vh]">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Server className="h-5 w-5" />
                        {t("page.hosts.order.title", "Manage Servers Order")}
                    </DialogTitle>
                    <DialogDescription>
                        {t(
                            "page.hosts.order.description",
                            "Drag and drop to reorder servers. Servers at the top will appear first in client configs."
                        )}
                    </DialogDescription>
                </DialogHeader>

                <ScrollArea className="h-[60vh] pr-4">
                    {orderedHosts.length === 0 ? (
                        <div className="flex items-center justify-center py-8 text-muted-foreground">
                            {t("page.hosts.order.no-hosts", "No hosts found")}
                        </div>
                    ) : (
                        <div className="flex flex-col gap-3">
                            {groupedHosts.map(([groupKey, group]) => (
                                <div
                                    key={groupKey}
                                    className="rounded-lg border bg-muted/40"
                                >
                                    <button
                                        type="button"
                                        className="flex w-full items-center justify-between px-3 py-2 hover:bg-muted/70"
                                        onClick={() => toggleGroup(groupKey)}
                                    >
                                        <div className="flex items-center gap-2">
                                            {collapsedGroups[groupKey] ? (
                                                <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                            ) : (
                                                <ChevronDown className="h-4 w-4 text-muted-foreground" />
                                            )}
                                            <span className="font-medium truncate">
                                                {group.label}
                                            </span>
                                            <Badge
                                                variant="outline"
                                                className="ml-2 text-xs"
                                            >
                                                {group.hosts.length}
                                            </Badge>
                                        </div>
                                    </button>

                                    {!collapsedGroups[groupKey] && (
                                        <div className="px-2 pb-2 pt-1">
                                            <Sortable
                                                value={group.hosts}
                                                onValueChange={(newOrder) =>
                                                    handleGroupReorder(groupKey, newOrder)
                                                }
                                            >
                                                <div className="flex flex-col gap-2">
                                                    {group.hosts.map((host) => (
                                                        <SortableItem
                                                            key={host.id}
                                                            value={host.id}
                                                            asChild
                                                        >
                                                            <div
                                                                className={cn(
                                                                    "flex items-center gap-3 p-3 rounded-lg border bg-card transition-colors hover:bg-accent/50",
                                                                    host.is_disabled && "opacity-50",
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
                                                                    className="shrink-0 w-8 justify-center font-mono text-xs"
                                                                >
                                                                    {(positionById.get(host.id) ?? 0) +
                                                                        1}
                                                                </Badge>

                                                                <div className="flex-1 min-w-0">
                                                                    <div className="flex items-center gap-2">
                                                                        {editingHostId === host.id ? (
                                                                            <input
                                                                                className="w-full bg-transparent border-b border-muted-foreground/40 focus:outline-none focus:border-primary text-sm font-medium"
                                                                                autoFocus
                                                                                value={editingRemark}
                                                                                onChange={(e) =>
                                                                                    setEditingRemark(
                                                                                        e.target.value,
                                                                                    )
                                                                                }
                                                                                onBlur={() =>
                                                                                    saveEditingRemark(
                                                                                        host,
                                                                                    )
                                                                                }
                                                                                onKeyDown={(e) => {
                                                                                    if (e.key === "Enter") {
                                                                                        e.preventDefault();
                                                                                        void saveEditingRemark(host);
                                                                                    }
                                                                                    if (e.key === "Escape") {
                                                                                        e.preventDefault();
                                                                                        cancelEditingRemark();
                                                                                    }
                                                                                }}
                                                                            />
                                                                        ) : (
                                                                            <button
                                                                                type="button"
                                                                                className="text-left font-medium truncate w-full"
                                                                                onClick={() =>
                                                                                    startEditingRemark(
                                                                                        host,
                                                                                    )
                                                                                }
                                                                            >
                                                                                {host.remark}
                                                                            </button>
                                                                        )}
                                                                    </div>
                                                                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                                                        <span className="truncate">
                                                                            {host.address}
                                                                            {host.port &&
                                                                                `:${host.port}`}
                                                                        </span>
                                                                    </div>
                                                                </div>

                                                                <div className="flex items-center gap-2 shrink-0">
                                                                    {host.is_disabled && (
                                                                        <Badge
                                                                            variant="secondary"
                                                                            className="text-xs"
                                                                        >
                                                                            {t("disabled")}
                                                                        </Badge>
                                                                    )}
                                                                    <Button
                                                                        variant="ghost"
                                                                        size="icon"
                                                                        onClick={() =>
                                                                            handleEditHost(host.id)
                                                                        }
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
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
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
                            ? t("page.hosts.order.saving", "Saving...")
                            : t("save")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

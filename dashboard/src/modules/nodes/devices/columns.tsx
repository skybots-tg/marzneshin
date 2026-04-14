import type { ColumnDef } from "@tanstack/react-table";
import type { DeviceInfoWithUser } from "../types";
import { DataTableColumnHeader } from "@marzneshin/libs/entity-table";
import { Badge } from "@marzneshin/common/components";
import i18n from "@marzneshin/features/i18n";
import { ArrowUp, ArrowDown } from "lucide-react";

const formatBytes = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${Number.parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

const formatTimestamp = (ts: number): string => {
    const date = new Date(ts * 1000);
    const now = Date.now();
    const diffMs = now - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return i18n.t("online");
    if (diffMin < 60) return `${diffMin}m`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d`;
};

export const nodeDeviceColumns: ColumnDef<DeviceInfoWithUser>[] = [
    {
        accessorKey: "uid",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("page.nodes.devices.user_col")} column={column} />
        ),
        cell: ({ row }) => (
            <span className="font-mono text-xs tabular-nums">#{row.original.uid}</span>
        ),
    },
    {
        accessorKey: "remote_ip",
        header: ({ column }) => (
            <DataTableColumnHeader title="IP" column={column} />
        ),
        cell: ({ row }) => (
            <span className="font-mono text-xs">{row.original.remote_ip}</span>
        ),
    },
    {
        accessorKey: "client_name",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("page.nodes.devices.client")} column={column} />
        ),
        cell: ({ row }) => (
            <span className="max-w-[120px] truncate block text-xs">{row.original.client_name}</span>
        ),
    },
    {
        accessorKey: "is_active",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("status")} column={column} />
        ),
        cell: ({ row }) => {
            const active = row.original.is_active;
            return (
                <div className="flex items-center gap-1.5">
                    <span className={`size-1.5 rounded-full ${active ? "bg-emerald-500" : "bg-muted-foreground/40"}`} />
                    <span className="text-xs">{active ? i18n.t("active") : i18n.t("inactive")}</span>
                </div>
            );
        },
    },
    {
        id: "traffic",
        accessorKey: "total_usage",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("total")} column={column} />
        ),
        cell: ({ row }) => (
            <div className="flex flex-col gap-0.5">
                <span className="text-xs font-medium tabular-nums">{formatBytes(row.original.total_usage)}</span>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground tabular-nums">
                    <span className="inline-flex items-center gap-0.5">
                        <ArrowUp className="size-2.5" />
                        {formatBytes(row.original.uplink)}
                    </span>
                    <span className="inline-flex items-center gap-0.5">
                        <ArrowDown className="size-2.5" />
                        {formatBytes(row.original.downlink)}
                    </span>
                </div>
            </div>
        ),
    },
    {
        accessorKey: "protocol",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("protocol")} column={column} />
        ),
        cell: ({ row }) => {
            const proto = row.original.protocol;
            return proto ? (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">{proto}</Badge>
            ) : (
                <span className="text-muted-foreground">—</span>
            );
        },
    },
    {
        accessorKey: "last_seen",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("last_seen")} column={column} />
        ),
        cell: ({ row }) => (
            <span className="text-xs text-muted-foreground tabular-nums">
                {formatTimestamp(row.original.last_seen)}
            </span>
        ),
    },
];

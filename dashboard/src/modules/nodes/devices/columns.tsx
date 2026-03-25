import type { ColumnDef } from "@tanstack/react-table";
import type { DeviceInfoWithUser } from "../types";
import { DataTableColumnHeader } from "@marzneshin/libs/entity-table";
import { Badge } from "@marzneshin/common/components";
import i18n from "@marzneshin/features/i18n";

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
            <span className="font-mono text-xs">#{row.original.uid}</span>
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
            <span className="max-w-[150px] truncate block">{row.original.client_name}</span>
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
                <Badge variant="outline" className="text-xs">{proto}</Badge>
            ) : (
                <span className="text-muted-foreground">—</span>
            );
        },
    },
    {
        accessorKey: "is_active",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("status")} column={column} />
        ),
        cell: ({ row }) => (
            <Badge variant={row.original.is_active ? "default" : "secondary"} className="text-xs">
                {row.original.is_active ? i18n.t("active") : i18n.t("inactive")}
            </Badge>
        ),
    },
    {
        accessorKey: "total_usage",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("total")} column={column} />
        ),
        cell: ({ row }) => (
            <span className="text-xs">{formatBytes(row.original.total_usage)}</span>
        ),
    },
    {
        accessorKey: "uplink",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("upload")} column={column} />
        ),
        cell: ({ row }) => (
            <span className="text-xs">{formatBytes(row.original.uplink)}</span>
        ),
    },
    {
        accessorKey: "downlink",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("download")} column={column} />
        ),
        cell: ({ row }) => (
            <span className="text-xs">{formatBytes(row.original.downlink)}</span>
        ),
    },
    {
        accessorKey: "last_seen",
        header: ({ column }) => (
            <DataTableColumnHeader title={i18n.t("last_seen")} column={column} />
        ),
        cell: ({ row }) => (
            <span className="text-xs text-muted-foreground">
                {formatTimestamp(row.original.last_seen)}
            </span>
        ),
    },
];

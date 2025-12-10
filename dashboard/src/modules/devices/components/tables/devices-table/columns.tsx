import type { ColumnDef } from "@tanstack/react-table";
import type { DeviceType } from "@marzneshin/modules/devices";
import { DataTableColumnHeader } from "@marzneshin/libs/entity-table";
import { Button, HStack, Badge } from "@marzneshin/common/components";
import { Pencil, Trash, Info, Smartphone, Monitor, Tablet } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

interface ColumnsProps {
    onEdit: (entity: DeviceType) => void;
    onDelete: (entity: DeviceType) => void;
    onOpen: (entity: DeviceType) => void;
}

const getDeviceIcon = (clientType: string) => {
    switch (clientType) {
        case "android":
        case "ios":
            return <Smartphone className="w-4 h-4" />;
        case "windows":
        case "macos":
        case "linux":
            return <Monitor className="w-4 h-4" />;
        default:
            return <Tablet className="w-4 h-4" />;
    }
};

const getClientTypeBadge = (clientType: string) => {
    const colors: Record<string, string> = {
        android: "bg-green-500/20 text-green-700 dark:text-green-300",
        ios: "bg-blue-500/20 text-blue-700 dark:text-blue-300",
        windows: "bg-purple-500/20 text-purple-700 dark:text-purple-300",
        macos: "bg-gray-500/20 text-gray-700 dark:text-gray-300",
        linux: "bg-orange-500/20 text-orange-700 dark:text-orange-300",
        other: "bg-gray-500/20 text-gray-700 dark:text-gray-300",
    };

    return (
        <Badge className={colors[clientType] || colors.other}>
            {getDeviceIcon(clientType)}
            <span className="ml-1">{clientType}</span>
        </Badge>
    );
};

const formatBytes = (bytes?: number) => {
    if (!bytes) return "0 B";
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`;
};

export const columns = ({ onEdit, onDelete, onOpen }: ColumnsProps): ColumnDef<DeviceType>[] => [
    {
        accessorKey: "display_name",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Device" />
        ),
        cell: ({ row }) => {
            const device = row.original;
            return (
                <div className="flex flex-col">
                    <span className="font-medium">
                        {device.display_name || device.client_name || "Unknown Device"}
                    </span>
                    {device.client_name && device.display_name && (
                        <span className="text-xs text-muted-foreground">{device.client_name}</span>
                    )}
                </div>
            );
        },
    },
    {
        accessorKey: "client_type",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Type" />
        ),
        cell: ({ row }) => getClientTypeBadge(row.original.client_type),
    },
    {
        accessorKey: "last_seen_at",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Last Seen" />
        ),
        cell: ({ row }) => {
            const date = new Date(row.original.last_seen_at);
            return (
                <span className="text-sm">
                    {formatDistanceToNow(date, { addSuffix: true })}
                </span>
            );
        },
    },
    {
        accessorKey: "total_traffic",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Traffic" />
        ),
        cell: ({ row }) => {
            const total = (row.original.total_upload_bytes || 0) + (row.original.total_download_bytes || 0);
            return <span className="text-sm">{formatBytes(total)}</span>;
        },
    },
    {
        accessorKey: "ip_count",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="IPs" />
        ),
        cell: ({ row }) => (
            <Badge variant="outline">
                {row.original.ip_count || 0}
            </Badge>
        ),
    },
    {
        accessorKey: "is_blocked",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Status" />
        ),
        cell: ({ row }) => {
            const device = row.original;
            return device.is_blocked ? (
                <Badge variant="destructive">Blocked</Badge>
            ) : (
                <Badge variant="default" className="bg-green-500/20 text-green-700 dark:text-green-300">
                    Active
                </Badge>
            );
        },
    },
    {
        accessorKey: "trust_level",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Trust" />
        ),
        cell: ({ row }) => {
            const level = row.original.trust_level;
            const color = level > 0 
                ? "bg-green-500/20 text-green-700 dark:text-green-300"
                : level < 0 
                ? "bg-red-500/20 text-red-700 dark:text-red-300"
                : "bg-gray-500/20 text-gray-700 dark:text-gray-300";
            
            return (
                <Badge className={color}>
                    {level > 0 ? "+" : ""}{level}
                </Badge>
            );
        },
    },
    {
        id: "actions",
        cell: ({ row }) => {
            const device = row.original;
            return (
                <HStack>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onOpen(device)}
                    >
                        <Info className="w-4 h-4" />
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onEdit(device)}
                    >
                        <Pencil className="w-4 h-4" />
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onDelete(device)}
                    >
                        <Trash className="w-4 h-4 text-destructive" />
                    </Button>
                </HStack>
            );
        },
    },
];


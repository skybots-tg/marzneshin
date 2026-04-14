import { ColumnDef } from "@tanstack/react-table"
import { NodesStatusBadge, NodeType, NodesStatus, useNodesResyncMutation } from "@marzneshin/modules/nodes"
import {
    DataTableActionsCell,
    DataTableColumnHeader
} from "@marzneshin/libs/entity-table"
import i18n from "@marzneshin/features/i18n"
import {
    type ColumnActions
} from "@marzneshin/libs/entity-table";
import {
    NoPropogationButton,
    Button,
    Badge,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger
} from "@marzneshin/common/components"
import { RefreshCw, ArrowLeftRight, Download, Shield } from 'lucide-react';
import { cn } from "@marzneshin/common/utils";
import { useState } from "react";
import { MigrationDialog, UpdateXrayDialog } from "@marzneshin/modules/nodes";

const ResyncButton = ({ node }: { node: NodeType }) => {
    const { mutate: resync, isPending } = useNodesResyncMutation();
    
    return (
        <Button
            variant="outline"
            size="sm"
            disabled={isPending || node.status !== "healthy"}
            onClick={(e) => {
                e.stopPropagation();
                resync(node);
            }}
            title={i18n.t('page.nodes.resync.title')}
        >
            <RefreshCw className={cn("size-4", isPending && "animate-spin")} />
        </Button>
    );
};

export const columns = (actions: ColumnActions<NodeType>): ColumnDef<NodeType>[] => ([
    {
        accessorKey: "name",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('name')} column={column} />,
    },
    {
        accessorKey: "status",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('status')} column={column} />,
        cell: ({ row }) => {
            const { status, message, adblock_enabled } = row.original;
            const statusBadge = status === 'unhealthy' && message ? (
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <span>
                                <NodesStatusBadge status={NodesStatus[status]} />
                            </span>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-xs">
                            <p className="text-destructive">{message}</p>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            ) : (
                <NodesStatusBadge status={NodesStatus[status]} />
            );
            return (
                <div className="flex items-center gap-1.5">
                    {statusBadge}
                    {adblock_enabled && (
                        <Badge variant="positive" className="h-6 gap-1">
                            <Shield className="size-3" />
                            Ad-block
                        </Badge>
                    )}
                </div>
            );
        },
    },
    {
        accessorKey: "address",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('address')} column={column} />,
        cell: ({ row }) => `${row.original.address}:${row.original.port}`
    },
    {
        accessorKey: "usage_coefficient",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('page.nodes.usage_coefficient')} column={column} />,
    },
    {
        id: "resync",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('page.nodes.resync.title')} column={column} />,
        cell: ({ row }) => (
            <div onClick={(e) => e.stopPropagation()}>
                <ResyncButton node={row.original} />
            </div>
        ),
    },
    {
        id: "migrate",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('page.nodes.migration.migrate')} column={column} />,
        cell: ({ row }) => {
            const [open, setOpen] = useState(false);
            return (
                <div onClick={(e) => e.stopPropagation()}>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                            e.stopPropagation();
                            setOpen(true);
                        }}
                        title={i18n.t('page.nodes.migration.migrate')}
                    >
                        <ArrowLeftRight className="size-4 mr-2" />
                        {i18n.t('page.nodes.migration.migrate')}
                    </Button>
                    {open && (
                        <MigrationDialog
                            open={open}
                            onOpenChange={setOpen}
                            node={row.original}
                        />
                    )}
                </div>
            );
        },
    },
    {
        id: "update-xray",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('page.nodes.update_xray.update')} column={column} />,
        cell: ({ row }) => {
            const [open, setOpen] = useState(false);
            return (
                <div onClick={(e) => e.stopPropagation()}>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                            e.stopPropagation();
                            setOpen(true);
                        }}
                        title={i18n.t('page.nodes.update_xray.update')}
                    >
                        <Download className="size-4 mr-2" />
                        {i18n.t('page.nodes.update_xray.update')}
                    </Button>
                    {open && (
                        <UpdateXrayDialog
                            open={open}
                            onOpenChange={setOpen}
                            node={row.original}
                        />
                    )}
                </div>
            );
        },
    },
    {
        id: "actions",
        cell: ({ row }) => {
            return (
                <NoPropogationButton row={row} actions={actions}>
                    <DataTableActionsCell {...actions} row={row} />
                </NoPropogationButton>
            );
        },
    }
]);

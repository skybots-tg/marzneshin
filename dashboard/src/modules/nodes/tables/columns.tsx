import { ColumnDef } from "@tanstack/react-table"
import { NodesStatusBadge, NodeType, NodesStatus, useNodesResyncMutation, useNodesUpdateMutation } from "@marzneshin/modules/nodes"
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
    Switch,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger
} from "@marzneshin/common/components"
import { RefreshCw, ArrowLeftRight, Download, Shield, AlertTriangle } from 'lucide-react';
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

const NodeEnabledSwitch = ({ node }: { node: NodeType }) => {
    const { mutate: updateNode, isPending } = useNodesUpdateMutation();
    const isEnabled = node.status !== "disabled";

    const handleToggle = (next: boolean) => {
        updateNode({
            ...node,
            status: next ? "unhealthy" : "disabled",
        });
    };

    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>
                    <span className="inline-flex">
                        <Switch
                            checked={isEnabled}
                            disabled={isPending}
                            onCheckedChange={handleToggle}
                            aria-label={i18n.t('page.nodes.enabled.toggle')}
                        />
                    </span>
                </TooltipTrigger>
                <TooltipContent>
                    {isEnabled
                        ? i18n.t('page.nodes.enabled.on_desc')
                        : i18n.t('page.nodes.enabled.off_desc')}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};

const AddressMissingBadge = () => (
    <TooltipProvider>
        <Tooltip>
            <TooltipTrigger asChild>
                <span className="inline-flex">
                    <Badge variant="destructive" className="h-6 gap-1">
                        <AlertTriangle className="size-3" />
                        {i18n.t('page.nodes.address_missing.label')}
                    </Badge>
                </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
                <p>{i18n.t('page.nodes.address_missing.desc')}</p>
            </TooltipContent>
        </Tooltip>
    </TooltipProvider>
);

export const columns = (actions: ColumnActions<NodeType>): ColumnDef<NodeType>[] => ([
    {
        id: "enabled",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('page.nodes.enabled.title')} column={column} />,
        cell: ({ row }) => (
            <div onClick={(e) => e.stopPropagation()}>
                <NodeEnabledSwitch node={row.original} />
            </div>
        ),
    },
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
        cell: ({ row }) => (
            <div className="flex items-center gap-1.5 flex-wrap">
                <span>{`${row.original.address}:${row.original.port}`}</span>
                {row.original.address_in_hosts === false && <AddressMissingBadge />}
            </div>
        ),
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

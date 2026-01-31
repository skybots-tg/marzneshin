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
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger
} from "@marzneshin/common/components"
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowsRotate, faSync } from '@fortawesome/free-solid-svg-icons';
import { useState } from "react";
import { MigrationDialog } from "@marzneshin/modules/nodes";

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
            <FontAwesomeIcon 
                icon={faSync} 
                className={isPending ? "animate-spin" : ""} 
            />
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
            const { status, message } = row.original;
            if (status === 'unhealthy' && message) {
                return (
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
                );
            }
            return <NodesStatusBadge status={NodesStatus[status]} />;
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
                        <FontAwesomeIcon icon={faArrowsRotate} className="mr-2" />
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

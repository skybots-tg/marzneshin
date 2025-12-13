import { ColumnDef } from "@tanstack/react-table"
import { NodesStatusBadge, NodeType, NodesStatus } from "@marzneshin/modules/nodes"
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
    Button
} from "@marzneshin/common/components"
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowsRotate } from '@fortawesome/free-solid-svg-icons';
import { useState } from "react";
import { MigrationDialog } from "@marzneshin/modules/nodes";

export const columns = (actions: ColumnActions<NodeType>): ColumnDef<NodeType>[] => ([
    {
        accessorKey: "name",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('name')} column={column} />,
    },
    {
        accessorKey: "status",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('status')} column={column} />,
        cell: ({ row }) => <NodesStatusBadge status={NodesStatus[row.original.status]} />,
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
        id: "migrate",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('page.nodes.migration.migrate')} column={column} />,
        cell: ({ row }) => {
            const [open, setOpen] = useState(false);
            return (
                <>
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
                    <MigrationDialog
                        open={open}
                        onOpenChange={setOpen}
                        node={row.original}
                    />
                </>
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

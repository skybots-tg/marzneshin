import { ColumnDef } from "@tanstack/react-table"
import { HostType } from "@marzneshin/modules/hosts"
import {
    DataTableActionsCell,
    DataTableColumnHeader,
} from "@marzneshin/libs/entity-table"
import i18n from "@marzneshin/features/i18n"
import { type ColumnActions } from "@marzneshin/libs/entity-table"
import { NoPropogationButton, Checkbox } from "@marzneshin/common/components"
import { InlineEditableCell } from "./inline-editable-cell"
import { HostToggleCell } from "./host-toggle-cell"

export const columns = (actions: ColumnActions<HostType>): ColumnDef<HostType>[] => ([
    {
        id: "select",
        header: ({ table }) => (
            <Checkbox
                checked={table.getIsAllPageRowsSelected()}
                onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
                onClick={(e) => e.stopPropagation()}
                aria-label="Select all"
            />
        ),
        cell: ({ row }) => (
            <Checkbox
                checked={row.getIsSelected()}
                onCheckedChange={(value) => row.toggleSelected(!!value)}
                onClick={(e) => e.stopPropagation()}
                aria-label="Select row"
            />
        ),
        enableSorting: false,
        enableHiding: false,
    },
    {
        accessorKey: "is_disabled",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('status')} column={column} />,
        cell: ({ row }) => <HostToggleCell host={row.original} />,
    },
    {
        accessorKey: "remark",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('name')} column={column} />,
        cell: ({ row }) => (
            <InlineEditableCell host={row.original} field="remark" />
        ),
    },
    {
        accessorKey: "weight",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('weight')} column={column} />,
        cell: ({ row }) => (
            <InlineEditableCell
                host={row.original}
                field="weight"
                inputType="number"
                displayValue={String(row.original.weight ?? 1)}
                emptyFallback="1"
            />
        ),
    },
    {
        accessorKey: "address",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('address')} column={column} />,
        cell: ({ row }) => (
            <InlineEditableCell host={row.original} field="address" />
        ),
    },
    {
        accessorKey: "port",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('port')} column={column} />,
        cell: ({ row }) => (
            <InlineEditableCell
                host={row.original}
                field="port"
                inputType="number"
                emptyFallback="—"
            />
        ),
    },
    {
        id: "actions",
        cell: ({ row }) => (
            <NoPropogationButton row={row} actions={actions}>
                <DataTableActionsCell {...actions} row={row} />
            </NoPropogationButton>
        ),
    },
]);

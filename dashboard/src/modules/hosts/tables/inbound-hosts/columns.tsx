import { ColumnDef } from "@tanstack/react-table"
import { HostType, useHostsUpdateMutation } from "@marzneshin/modules/hosts"
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
    Input,
} from "@marzneshin/common/components"
import { useState, useRef, useEffect } from "react"
import { useQueryClient, useQuery } from "@tanstack/react-query"
import { fetchHost, HostQueryFetchKey } from "@marzneshin/modules/hosts"

const InlineEditableRemarkCell = ({ host }: { host: HostType }) => {
    const [isEditing, setIsEditing] = useState(false)
    const [value, setValue] = useState(host.remark || "")
    const inputRef = useRef<HTMLInputElement>(null)
    const updateMutation = useHostsUpdateMutation()
    const queryClient = useQueryClient()
    const { data: fullHost, refetch: refetchHost } = useQuery({
        queryKey: [HostQueryFetchKey, host.id!],
        queryFn: () => fetchHost({ queryKey: [HostQueryFetchKey, host.id!] }),
        enabled: false,
        initialData: undefined
    })

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditing])

    const handleStartEdit = async (e: React.MouseEvent) => {
        e.stopPropagation()
        if (!host.id) return
        
        // Загружаем полный хост перед началом редактирования
        const result = await refetchHost()
        if (result.data) {
            setValue(result.data.remark || "")
            setIsEditing(true)
        }
    }

    const handleSave = async () => {
        if (!host.id || !fullHost) {
            setIsEditing(false)
            return
        }
        
        const trimmedValue = value.trim()
        if (trimmedValue === fullHost.remark) {
            setIsEditing(false)
            return
        }

        if (!trimmedValue) {
            setValue(fullHost.remark || "")
            setIsEditing(false)
            return
        }

        try {
            await updateMutation.mutateAsync({
                hostId: host.id,
                host: {
                    ...fullHost,
                    remark: trimmedValue,
                }
            })
            setIsEditing(false)
            queryClient.invalidateQueries({ queryKey: ["inbounds"] })
        } catch (error) {
            setValue(fullHost.remark || "")
            setIsEditing(false)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault()
            handleSave()
        } else if (e.key === "Escape") {
            setValue(host.remark || "")
            setIsEditing(false)
        }
    }

    if (isEditing) {
        return (
            <Input
                ref={inputRef}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onBlur={handleSave}
                onKeyDown={handleKeyDown}
                className="h-8"
                disabled={updateMutation.isPending}
            />
        )
    }

    return (
        <span
            className="cursor-pointer hover:underline"
            onClick={handleStartEdit}
        >
            {host.remark}
        </span>
    )
}

export const columns = (actions: ColumnActions<HostType>): ColumnDef<HostType>[] => ([
    {
        accessorKey: "remark",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('name')} column={column} />,
        cell: ({ row }) => {
            const host = row.original
            return <InlineEditableRemarkCell host={host} />
        },
    },
    {
        accessorKey: "weight",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('weight')} column={column} />,
        cell: ({ row }) => {
            return row.original.weight ?? 1
        },
    },
    {
        accessorKey: "address",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('address')} column={column} />,
    },
    {
        accessorKey: "port",
        header: ({ column }) => <DataTableColumnHeader title={i18n.t('port')} column={column} />,
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

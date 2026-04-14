import { useEntityTableContext } from "@marzneshin/libs/entity-table/contexts"
import { Button } from "@marzneshin/common/components"
import { Power, PowerOff, Trash2 } from "lucide-react"
import { useTranslation } from "react-i18next"
import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import {
    HostType,
    fetchHost,
    HostQueryFetchKey,
    useHostsUpdateMutation,
    useHostsDeletionMutation,
} from "@marzneshin/modules/hosts"

export const BulkActionsToolbar = () => {
    const { t } = useTranslation()
    const { table } = useEntityTableContext()
    const updateMutation = useHostsUpdateMutation()
    const deleteMutation = useHostsDeletionMutation()
    const queryClient = useQueryClient()
    const [loading, setLoading] = useState(false)

    const selectedRows = table.getSelectedRowModel().rows
    const selectedCount = selectedRows.length

    if (selectedCount === 0) return null

    const getSelectedHosts = (): HostType[] =>
        selectedRows.map((row: any) => row.original as HostType)

    const bulkSetDisabled = async (disabled: boolean) => {
        setLoading(true)
        try {
            const hosts = getSelectedHosts()
            await Promise.all(
                hosts
                    .filter((h) => h.id && h.is_disabled !== disabled)
                    .map(async (h) => {
                        const fullHost = await fetchHost({ queryKey: [HostQueryFetchKey, h.id!] })
                        return updateMutation.mutateAsync({
                            hostId: h.id!,
                            host: { ...fullHost, is_disabled: disabled },
                        })
                    })
            )
            queryClient.invalidateQueries({ queryKey: ["inbounds"] })
            table.toggleAllRowsSelected(false)
        } finally {
            setLoading(false)
        }
    }

    const bulkDelete = async () => {
        setLoading(true)
        try {
            const hosts = getSelectedHosts()
            await Promise.all(
                hosts
                    .filter((h) => h.id)
                    .map((h) => deleteMutation.mutateAsync(h))
            )
            queryClient.invalidateQueries({ queryKey: ["inbounds"] })
            table.toggleAllRowsSelected(false)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="flex items-center gap-2 rounded-md border bg-muted/50 px-3 py-1.5 text-sm">
            <span className="text-muted-foreground whitespace-nowrap">
                {t("selected")}: {selectedCount}
            </span>
            <Button
                variant="outline"
                size="sm"
                onClick={() => bulkSetDisabled(false)}
                disabled={loading}
                className="gap-1"
            >
                <Power className="h-3.5 w-3.5" />
                {t("enable")}
            </Button>
            <Button
                variant="outline"
                size="sm"
                onClick={() => bulkSetDisabled(true)}
                disabled={loading}
                className="gap-1"
            >
                <PowerOff className="h-3.5 w-3.5" />
                {t("disable")}
            </Button>
            <Button
                variant="destructive"
                size="sm"
                onClick={bulkDelete}
                disabled={loading}
                className="gap-1"
            >
                <Trash2 className="h-3.5 w-3.5" />
                {t("delete")}
            </Button>
        </div>
    )
}

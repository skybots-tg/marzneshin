import { useCallback } from "react"
import { useQueryClient, useQuery } from "@tanstack/react-query"
import { Switch } from "@marzneshin/common/components"
import {
    HostType,
    useHostsUpdateMutation,
    fetchHost,
    HostQueryFetchKey,
} from "@marzneshin/modules/hosts"

export const HostToggleCell = ({ host }: { host: HostType }) => {
    const updateMutation = useHostsUpdateMutation()
    const queryClient = useQueryClient()

    const { refetch: refetchHost } = useQuery({
        queryKey: [HostQueryFetchKey, host.id!],
        queryFn: () => fetchHost({ queryKey: [HostQueryFetchKey, host.id!] }),
        enabled: false,
        initialData: undefined,
    })

    const handleToggle = useCallback(async (checked: boolean) => {
        if (!host.id) return
        const result = await refetchHost()
        if (!result.data) return

        try {
            await updateMutation.mutateAsync({
                hostId: host.id,
                host: { ...result.data, is_disabled: !checked },
            })
            queryClient.invalidateQueries({ queryKey: ["inbounds"] })
        } catch { /* toast handled by mutation */ }
    }, [host.id, refetchHost, updateMutation, queryClient])

    return (
        <Switch
            checked={!host.is_disabled}
            onCheckedChange={handleToggle}
            disabled={updateMutation.isPending}
            onClick={(e) => e.stopPropagation()}
        />
    )
}

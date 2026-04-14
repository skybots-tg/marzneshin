import type { NodeFilteringConfig, DnsProvider } from "@marzneshin/modules/nodes";
import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";
import { FilteringQueryKey } from "./filtering.query";

interface UpdateFilteringParams {
    nodeId: number;
    adblock_enabled?: boolean;
    dns_provider?: DnsProvider;
    dns_address?: string | null;
    adguard_home_port?: number;
}

async function fetchUpdateFiltering({
    nodeId,
    ...body
}: UpdateFilteringParams): Promise<NodeFilteringConfig> {
    return fetch(`/nodes/${nodeId}/filtering`, {
        method: "put",
        body,
    });
}

export const useFilteringMutation = () => {
    return useMutation({
        mutationKey: [FilteringQueryKey, "update"],
        mutationFn: fetchUpdateFiltering,
        onSuccess: () => {
            toast.success(i18n.t("page.nodes.filtering.save_success"));
            queryClient.invalidateQueries({ queryKey: [FilteringQueryKey] });
            queryClient.invalidateQueries({ queryKey: ["nodes"] });
        },
        onError: (error: Error) => {
            toast.error(i18n.t("page.nodes.filtering.save_error"), {
                description: error.message,
            });
        },
    });
};

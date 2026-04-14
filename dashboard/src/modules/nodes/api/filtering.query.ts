import type { NodeFilteringConfig } from "@marzneshin/modules/nodes";
import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";

export const FilteringQueryKey = "node-filtering";

export async function fetchFilteringConfig(
    nodeId: number,
): Promise<NodeFilteringConfig> {
    return fetch(`/nodes/${nodeId}/filtering`);
}

export const useFilteringConfigQuery = (nodeId: number) => {
    return useQuery({
        queryKey: [FilteringQueryKey, nodeId],
        queryFn: () => fetchFilteringConfig(nodeId),
        initialData: {
            adblock_enabled: false,
            dns_provider: "adguard_dns_public" as const,
            dns_address: null,
            adguard_home_port: 5353,
            adguard_home_installed: false,
        },
    });
};

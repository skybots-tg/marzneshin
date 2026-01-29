import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";

export interface HostWithInbound {
    id: number;
    remark: string;
    address: string;
    port: number | null;
    weight: number;
    is_disabled: boolean;
    inbound_id: number | null;
    protocol?: string;
}

interface AllHostsResponse {
    items: HostWithInbound[];
    total: number;
    page: number;
    size: number;
    pages: number;
}

export async function fetchAllHosts(): Promise<HostWithInbound[]> {
    const result: AllHostsResponse = await fetch("/inbounds/hosts", {
        query: {
            page: 1,
            size: 500, // Get all hosts
            order_by: "weight",
            descending: true,
        },
    });
    return result.items;
}

export const useAllHostsQuery = () => {
    return useQuery({
        queryKey: ["all-hosts"],
        queryFn: fetchAllHosts,
        initialData: [],
    });
};

import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";
import type { UserDevicesResponse, DeviceInfoWithUser } from "../types";
import type {
    DoubleEntityQueryKeyType,
    FetchEntityReturn,
} from "@marzneshin/libs/entity-table";

export async function fetchUserDevices({
    queryKey,
}: {
    queryKey: [string, number, number, boolean?];
}): Promise<UserDevicesResponse> {
    const [, nodeId, userId, activeOnly] = queryKey;
    const params = new URLSearchParams();
    if (activeOnly) {
        params.append("active_only", "true");
    }
    const url = `/nodes/${nodeId}/devices/${userId}${params.toString() ? `?${params.toString()}` : ""}`;
    return await fetch(url);
}

export async function fetchNodeDevices({
    queryKey,
}: DoubleEntityQueryKeyType): FetchEntityReturn<DeviceInfoWithUser> {
    const nodeId = queryKey[1];
    const pagination = queryKey[2];
    const primaryFilter = queryKey[3];
    const { sortBy, desc } = queryKey[4] ?? { sortBy: "last_seen", desc: true };
    const { filters } = queryKey[5] ?? { filters: {} };
    return fetch(`/nodes/${nodeId}/devices`, {
        query: {
            ...pagination,
            search: primaryFilter || undefined,
            sort_by: sortBy,
            descending: desc,
            ...filters,
        },
    }).then((result: { items: DeviceInfoWithUser[]; pages: number }) => ({
        entities: result.items,
        pageCount: result.pages,
    }));
}

export const UserDevicesQueryKey = "user-devices";
export const NodeDevicesQueryKey = "node-devices";

export const useUserDevicesQuery = ({
    nodeId,
    userId,
    activeOnly = false,
    enabled = true,
}: {
    nodeId: number;
    userId: number;
    activeOnly?: boolean;
    enabled?: boolean;
}) => {
    return useQuery({
        queryKey: [UserDevicesQueryKey, nodeId, userId, activeOnly],
        queryFn: fetchUserDevices,
        enabled,
    });
};


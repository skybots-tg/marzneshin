import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";
import type { UserDevicesResponse, AllUsersDevicesResponse } from "../types";

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

export async function fetchAllDevices({
    queryKey,
}: {
    queryKey: [string, number];
}): Promise<AllUsersDevicesResponse> {
    const [, nodeId] = queryKey;
    return await fetch(`/nodes/${nodeId}/devices`);
}

export const UserDevicesQueryKey = "user-devices";
export const AllDevicesQueryKey = "all-devices";

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

export const useAllDevicesQuery = ({
    nodeId,
    enabled = true,
}: {
    nodeId: number;
    enabled?: boolean;
}) => {
    return useQuery({
        queryKey: [AllDevicesQueryKey, nodeId],
        queryFn: fetchAllDevices,
        enabled,
    });
};


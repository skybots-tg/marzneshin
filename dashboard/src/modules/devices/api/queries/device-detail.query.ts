import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";
import type { DeviceDetailType } from "@marzneshin/modules/devices";

export async function fetchDeviceDetail(userId: number, deviceId: number): Promise<DeviceDetailType> {
    return fetch(`/admin/users/${userId}/devices/${deviceId}`);
}

export const DeviceDetailQueryKey = "device-detail";

export const useDeviceDetailQuery = (userId: number, deviceId: number) => {
    return useQuery({
        queryKey: [DeviceDetailQueryKey, userId, deviceId],
        queryFn: () => fetchDeviceDetail(userId, deviceId),
        enabled: !!userId && !!deviceId,
    })
}


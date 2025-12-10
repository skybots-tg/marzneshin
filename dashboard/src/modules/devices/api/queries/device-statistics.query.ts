import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";
import type { DeviceStatisticsType } from "@marzneshin/modules/devices";

export async function fetchDeviceStatistics(userId: number | string): Promise<DeviceStatisticsType> {
    return fetch(`/admin/users/${userId}/devices/statistics`);
}

export const DeviceStatisticsQueryKey = "device-statistics";

export const useDeviceStatisticsQuery = (userId: number | string) => {
    return useQuery({
        queryKey: [DeviceStatisticsQueryKey, String(userId)],
        queryFn: () => fetchDeviceStatistics(userId),
        enabled: !!userId,
    })
}


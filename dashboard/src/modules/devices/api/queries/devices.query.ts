import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";
import { DeviceType } from "@marzneshin/modules/devices";
import {
    FetchEntityReturn,
    UseEntityQueryProps,
    EntityQueryKeyType
} from "@marzneshin/libs/entity-table";

export type SortDeviceBy = "last_seen_at" | "first_seen_at" | "client_name"

export async function fetchUserDevices({ queryKey }: EntityQueryKeyType): FetchEntityReturn<DeviceType> {
    const pagination = queryKey[1];
    const userId = queryKey[2];
    const filters = queryKey[4].filters;
    
    return fetch(`/admin/users/${userId}/devices`, {
        query: {
            ...filters,
        }
    }).then((result) => {
        // API returns array, not paginated response
        return {
            entities: result,
            pageCount: 1
        };
    });
}

export const UserDevicesQueryFetchKey = "user-devices";

export const useUserDevicesQuery = (userId: number, {
    page, size, sortBy = "last_seen_at", desc = false, filters = {}
}: UseEntityQueryProps) => {
    return useQuery({
        queryKey: [UserDevicesQueryFetchKey, { page, size }, userId, { sortBy, desc }, { filters }],
        queryFn: fetchUserDevices,
        initialData: { entities: [], pageCount: 0 },
        enabled: !!userId,
    })
}


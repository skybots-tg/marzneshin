import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";
import {
    UserDevicesQueryFetchKey,
    DeviceDetailQueryKey,
    DeviceMutationType
} from "@marzneshin/modules/devices";

interface UpdateDeviceParams {
    userId: number;
    deviceId: number;
    data: DeviceMutationType;
}

export async function updateDevice({ userId, deviceId, data }: UpdateDeviceParams): Promise<DeviceMutationType> {
    return fetch(`/admin/users/${userId}/devices/${deviceId}`, { 
        method: 'patch', 
        body: data 
    }).then((device) => {
        return device;
    });
}

const handleError = (error: Error, value: UpdateDeviceParams) => {
    toast.error(
        i18n.t('Device update failed'),
        {
            description: error.message
        })
}

const handleSuccess = (data: any, value: UpdateDeviceParams) => {
    toast.success(
        i18n.t('Device updated successfully'),
        {
            description: i18n.t('Device settings have been updated')
        })
    queryClient.invalidateQueries({ queryKey: [UserDevicesQueryFetchKey] })
    queryClient.invalidateQueries({ queryKey: [DeviceDetailQueryKey, value.userId, value.deviceId] })
}

const DevicesUpdateFetchKey = "devices-update";

export const useDevicesUpdateMutation = () => {
    return useMutation({
        mutationKey: [DevicesUpdateFetchKey],
        mutationFn: updateDevice,
        onError: handleError,
        onSuccess: handleSuccess,
    })
}


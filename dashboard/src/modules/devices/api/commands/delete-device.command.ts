import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";
import { UserDevicesQueryFetchKey } from "@marzneshin/modules/devices";

interface DeleteDeviceParams {
    userId: number | string;
    deviceId: number;
}

export async function deleteDevice({ userId, deviceId }: DeleteDeviceParams): Promise<void> {
    return fetch(`/admin/users/${userId}/devices/${deviceId}`, { 
        method: 'delete'
    });
}

const handleError = (error: Error) => {
    toast.error(
        i18n.t('Device deletion failed'),
        {
            description: error.message
        })
}

const handleSuccess = () => {
    toast.success(
        i18n.t('Device deleted'),
        {
            description: i18n.t('The device has been removed')
        })
    queryClient.invalidateQueries({ queryKey: [UserDevicesQueryFetchKey] })
}

const DevicesDeleteFetchKey = "devices-delete";

export const useDevicesDeleteMutation = () => {
    return useMutation({
        mutationKey: [DevicesDeleteFetchKey],
        mutationFn: deleteDevice,
        onError: handleError,
        onSuccess: handleSuccess,
    })
}


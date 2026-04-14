import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";

export type SSHPinStatus = {
    configured: boolean;
    has_credentials: boolean;
};

export const SSHPinQueryKey = "ssh-pin-status";

export async function fetchSSHPinStatus(): Promise<SSHPinStatus> {
    return fetch("/system/settings/ssh-pin");
}

export const useSSHPinStatusQuery = () => {
    return useQuery({
        queryKey: [SSHPinQueryKey],
        queryFn: fetchSSHPinStatus,
        initialData: { configured: false, has_credentials: false },
    });
};

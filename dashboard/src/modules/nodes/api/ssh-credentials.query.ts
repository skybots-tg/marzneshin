import type { SSHCredentialsInfo } from "@marzneshin/modules/nodes";
import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";

export const SSHCredsQueryKey = "node-ssh-creds";

export async function fetchSSHCredsInfo(
    nodeId: number,
): Promise<SSHCredentialsInfo> {
    return fetch(`/nodes/${nodeId}/ssh-credentials`);
}

export const useSSHCredsQuery = (nodeId: number) => {
    return useQuery({
        queryKey: [SSHCredsQueryKey, nodeId],
        queryFn: () => fetchSSHCredsInfo(nodeId),
        initialData: { exists: false },
    });
};

import type { SSHCredentialsInfo } from "@marzneshin/modules/nodes";
import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";
import { SSHCredsQueryKey } from "./ssh-credentials.query";

interface StoreSSHCredsParams {
    nodeId: number;
    ssh_user: string;
    ssh_port: number;
    ssh_password?: string | null;
    ssh_key?: string | null;
    pin: string;
}

async function fetchStoreSSHCreds({
    nodeId,
    ...body
}: StoreSSHCredsParams): Promise<SSHCredentialsInfo> {
    return fetch(`/nodes/${nodeId}/ssh-credentials`, {
        method: "post",
        body,
    });
}

async function fetchDeleteSSHCreds(nodeId: number): Promise<void> {
    return fetch(`/nodes/${nodeId}/ssh-credentials`, {
        method: "delete",
    });
}

export const useStoreSSHCredsMutation = () => {
    return useMutation({
        mutationKey: [SSHCredsQueryKey, "store"],
        mutationFn: fetchStoreSSHCreds,
        onSuccess: () => {
            toast.success(i18n.t("page.nodes.filtering.ssh.save_success"));
            queryClient.invalidateQueries({ queryKey: [SSHCredsQueryKey] });
        },
        onError: (error: Error) => {
            toast.error(i18n.t("page.nodes.filtering.ssh.save_error"), {
                description: error.message,
            });
        },
    });
};

export const useDeleteSSHCredsMutation = () => {
    return useMutation({
        mutationKey: [SSHCredsQueryKey, "delete"],
        mutationFn: fetchDeleteSSHCreds,
        onSuccess: () => {
            toast.success(i18n.t("page.nodes.filtering.ssh.delete_success"));
            queryClient.invalidateQueries({ queryKey: [SSHCredsQueryKey] });
        },
        onError: (error: Error) => {
            toast.error(i18n.t("page.nodes.filtering.ssh.delete_error"), {
                description: error.message,
            });
        },
    });
};

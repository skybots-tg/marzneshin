import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";
import { type SSHPinStatus, SSHPinQueryKey } from "./ssh-pin.query";

async function fetchSetupSSHPin(pin: string): Promise<SSHPinStatus> {
    return fetch("/system/settings/ssh-pin", {
        method: "post",
        body: { pin },
    });
}

async function fetchDeleteSSHPin(): Promise<SSHPinStatus> {
    return fetch("/system/settings/ssh-pin", {
        method: "delete",
    });
}

export const useSetupSSHPinMutation = () => {
    return useMutation({
        mutationKey: [SSHPinQueryKey, "setup"],
        mutationFn: fetchSetupSSHPin,
        onSuccess: () => {
            toast.success(i18n.t("page.settings.ssh_pin.setup_success"));
            queryClient.invalidateQueries({ queryKey: [SSHPinQueryKey] });
        },
        onError: (error: Error) => {
            toast.error(i18n.t("page.settings.ssh_pin.setup_error"), {
                description: error.message,
            });
        },
    });
};

export const useDeleteSSHPinMutation = () => {
    return useMutation({
        mutationKey: [SSHPinQueryKey, "delete"],
        mutationFn: fetchDeleteSSHPin,
        onSuccess: () => {
            toast.success(i18n.t("page.settings.ssh_pin.delete_success"));
            queryClient.invalidateQueries({ queryKey: [SSHPinQueryKey] });
        },
        onError: (error: Error) => {
            toast.error(i18n.t("page.settings.ssh_pin.delete_error"), {
                description: error.message,
            });
        },
    });
};

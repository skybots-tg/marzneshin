import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";

interface HostWeightUpdate {
    id: number;
    weight: number;
}

interface UpdateHostsWeightsRequest {
    hosts: HostWeightUpdate[];
}

interface UpdateHostsWeightsResponse {
    updated: HostWeightUpdate[];
}

export async function fetchUpdateHostsWeights(
    request: UpdateHostsWeightsRequest
): Promise<UpdateHostsWeightsResponse> {
    return fetch("/inbounds/hosts/weights", {
        method: "put",
        body: request,
    });
}

const handleError = (error: Error) => {
    toast.error(i18n.t("page.hosts.order.update-error", "Failed to update hosts order"), {
        description: error.message,
    });
};

const handleSuccess = () => {
    toast.success(i18n.t("page.hosts.order.update-success", "Hosts order has been updated"));
    queryClient.invalidateQueries({ queryKey: ["inbounds"] });
    queryClient.invalidateQueries({ queryKey: ["all-hosts"] });
};

export const useUpdateHostsWeightsMutation = () => {
    return useMutation({
        mutationKey: ["hosts-weights"],
        onError: handleError,
        onSuccess: handleSuccess,
        mutationFn: fetchUpdateHostsWeights,
    });
};

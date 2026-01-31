import { NodeType, NodesQueryFetchKey } from "@marzneshin/modules/nodes";
import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";

export async function fetchResyncNode(node: NodeType): Promise<{ status: string; message: string }> {
    return fetch(`/nodes/${node.id}/resync`, { method: 'post' });
}

const NodesResyncFetchKey = "nodes-resync";

const handleError = (error: Error, value: NodeType) => {
    toast.error(
        i18n.t('page.nodes.resync.error', { name: value.name }),
        {
            description: error.message
        })
}

const handleSuccess = (data: { status: string; message: string }, value: NodeType) => {
    toast.success(
        i18n.t('page.nodes.resync.success', { name: value.name }),
        {
            description: data.message
        })
    queryClient.invalidateQueries({ queryKey: [NodesQueryFetchKey] })
}

export const useNodesResyncMutation = () => {
    return useMutation({
        mutationKey: [NodesResyncFetchKey],
        mutationFn: fetchResyncNode,
        onError: handleError,
        onSuccess: handleSuccess,
    })
}

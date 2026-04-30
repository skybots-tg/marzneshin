import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";

export type NodeSystemStatsType = {
    cpu_percent: number;
    cpu_count: number;
    mem_total: number;
    mem_used: number;
    mem_available: number;
    mem_percent: number;
    disk_total: number;
    disk_used: number;
    disk_free: number;
    disk_percent: number;
    disk_path: string;
    load_avg_1: number;
    load_avg_5: number;
    load_avg_15: number;
    uptime_seconds: number;
    collected_at: number;
};

type Status = "ok" | "unavailable" | "unsupported" | "loading";

export type NodeSystemStatsResult = {
    stats: NodeSystemStatsType | null;
    status: Status;
};

type QueryKey = readonly ["nodes", number, "system"];

async function fetchNodeSystemStats({
    queryKey,
}: { queryKey: QueryKey }): Promise<NodeSystemStatsResult> {
    const nodeId = queryKey[1];
    try {
        const stats = await fetch(`/nodes/${nodeId}/system`);
        return { stats, status: "ok" };
    } catch (err: unknown) {
        // ofetch rejects with FetchError whose status is exposed both as
        // `.statusCode` and `.response.status` depending on the version;
        // we check both to be robust. Fall back to "unavailable" so the
        // UI degrades gracefully for transient errors.
        const e = err as {
            statusCode?: number;
            status?: number;
            response?: { status?: number };
        };
        const status = e?.statusCode ?? e?.status ?? e?.response?.status;
        if (status === 501) return { stats: null, status: "unsupported" };
        return { stats: null, status: "unavailable" };
    }
}

export const useNodeSystemStatsQuery = (
    nodeId: number,
    opts?: { enabled?: boolean }
) =>
    useQuery({
        queryKey: ["nodes", nodeId, "system"] as const,
        queryFn: fetchNodeSystemStats,
        enabled: opts?.enabled ?? true,
        // 30 s polling: the stats are cheap (panel + node both cache),
        // and the user cares about a fresh snapshot, not real-time.
        refetchInterval: 30_000,
        staleTime: 15_000,
        retry: false,
    });

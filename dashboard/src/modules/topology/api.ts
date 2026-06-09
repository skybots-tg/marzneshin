export interface TopologyEntry {
    node_id: number;
    name: string;
    address: string;
    status: string;
    tier: "universal" | "elite";
    index: number;
    key: string;
    exit_isos: string[];
    missing_isos: string[];
    exit_count: number;
}

export interface FastExit {
    iso: string;
    label: string;
    node_count: number;
}

export interface NodeRef {
    node_id: number;
    name: string;
    address?: string;
    status?: string;
}

export interface DonorNode {
    node_id: number;
    name: string;
    tier: string;
    index: number;
    key: string;
    exit_count: number;
}

export interface Topology {
    exit_countries: string[];
    entries: TopologyEntry[];
    fast: FastExit[];
    promote_candidates: NodeRef[];
    donor_nodes: DonorNode[];
}

export interface ExitPlan {
    error?: string;
    exit_node: { node_id: number; name: string; address: string; status: string };
    iso: string;
    exit_already_in_fleet: boolean;
    grpc_reachable: boolean;
    reality_listeners: {
        tag: string;
        port: number;
        serverNames: string[];
        shortIds: string[];
    }[];
    targets_total: number;
    already_have: string[];
    pending: { key: string; node_id: number; name: string }[];
    apply_command: string;
    note: string;
}

const authHeaders = (): Record<string, string> => {
    const token = localStorage.getItem("token") || "";
    return {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
    };
};

export async function fetchTopology(): Promise<Topology> {
    const res = await fetch("/api/topology", { headers: authHeaders() });
    if (!res.ok) throw new Error(`topology ${res.status}`);
    return res.json();
}

export async function planExitCountry(body: {
    exit_node_id: number;
    flag_iso: string;
    label: string;
    include_universal: boolean;
    include_elite: boolean;
}): Promise<ExitPlan> {
    const res = await fetch("/api/topology/plan-exit-country", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(body),
    });
    return res.json();
}

export interface SSEHandlers {
    onLog?: (msg: string) => void;
    onStep?: (step: { name: string; ok: boolean; detail: Record<string, unknown> }) => void;
    onComplete?: (success: boolean, failedStep?: string) => void;
    onError?: (msg: string) => void;
}

/** Stream an SSE POST endpoint, parsing `event:`/`data:` frames. */
export async function streamSSE(
    url: string,
    body: unknown,
    handlers: SSEHandlers,
    signal: AbortSignal,
): Promise<void> {
    const res = await fetch(url, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(body),
        signal,
    });
    if (!res.ok || !res.body) {
        handlers.onError?.(`request failed (${res.status})`);
        handlers.onComplete?.(false);
        return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
            let event = "message";
            let data = "";
            for (const line of part.split("\n")) {
                if (line.startsWith("event: ")) event = line.slice(7);
                else if (line.startsWith("data: ")) data = line.slice(6);
            }
            if (!data) continue;
            try {
                const parsed = JSON.parse(data);
                if (event === "log") handlers.onLog?.(parsed.message);
                else if (event === "step") handlers.onStep?.(parsed);
                else if (event === "error") handlers.onError?.(parsed.message);
                else if (event === "complete")
                    handlers.onComplete?.(parsed.success, parsed.failed_step);
            } catch {
                /* ignore malformed frame */
            }
        }
    }
}

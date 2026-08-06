export type Verdict = "pass" | "wrong_geo" | "fail" | "skip";

export interface BridgeHost {
    host_id: number;
    remark: string;
    is_disabled: boolean;
    weight: number;
    tier: string;
    tier_index: number;
    entry_key: string;
    slot: string;
    iso: string | null;
    variant: "tcp" | "xhttp";
    inbound_id: number;
    tag: string;
    node_id: number;
    node_name: string;
    node_status: string;
    address: string;
    port: number | null;
    is_bridge: boolean;
    verdict: Verdict;
    country?: string;
    expected_country?: string;
    egress_ip?: string;
    error?: string;
    elapsed?: number;
    partial?: boolean;
    vantages_ok?: string[];
    vantages_tried?: string[];
}

export interface MatrixCell {
    pass: number;
    wrong_geo: number;
    fail: number;
    skip: number;
    enabled: number;
    host_ids: number[];
}

export interface BridgeGap {
    entry_key: string;
    tier: string;
    index: number;
    node_id: number;
    node_name: string;
    address: string;
    slot: string;
    reason: "missing" | "blocked";
    fillable: boolean;
    dead_host_ids: number[];
    donors: string[];
    reachable_slots?: string[];
}

export interface BridgeHealthReport {
    available: boolean;
    hint?: string;
    scan_running: boolean;
    generated_at?: number;
    age_sec?: number;
    stale?: boolean;
    elapsed_sec?: number;
    total?: number;
    counts?: Partial<Record<Verdict, number>>;
    hosts?: BridgeHost[];
    matrix?: Record<string, Record<string, MatrixCell>>;
    gaps?: BridgeGap[];
    pending?: { disable: number[]; enable: number[] };
    shadowed?: number[];
    duplicates?: { remark: string; host_ids: number[] }[];
    apply_blocked?: boolean;
    vantages?: { node_id: number; name: string; address: string; error?: string }[];
}

export interface ApplyResult {
    error?: string;
    disabled?: number[];
    enabled?: number[];
    changed?: number;
}

const authHeaders = (): Record<string, string> => {
    const token = localStorage.getItem("token") || "";
    return {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
    };
};

export async function fetchBridgeHealth(): Promise<BridgeHealthReport> {
    const res = await fetch("/api/bridge-health", { headers: authHeaders() });
    if (!res.ok) throw new Error(`bridge-health ${res.status}`);
    return res.json();
}

export async function applyBridgeHealth(body: {
    disable_ids?: number[];
    enable_ids?: number[];
    force?: boolean;
}): Promise<ApplyResult> {
    const res = await fetch("/api/bridge-health/apply", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(body),
    });
    return res.json();
}

export async function startBridgeScan(applyFixes: boolean): Promise<{
    queued: boolean;
    reason?: string;
}> {
    const res = await fetch("/api/bridge-health/scan", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ tier: "universal", apply_fixes: applyFixes }),
    });
    return res.json();
}

export async function fetchBridgeScanLog(): Promise<{
    running: boolean;
    lines: string[];
}> {
    const res = await fetch("/api/bridge-health/log", { headers: authHeaders() });
    if (!res.ok) throw new Error(`bridge-health log ${res.status}`);
    return res.json();
}

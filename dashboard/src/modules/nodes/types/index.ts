import type { StatusType } from "@marzneshin/common/types/status";
import { PowerOff, Zap, ZapOff } from "lucide-react";
import { z } from "zod";

export const NodesStatus = {
    healthy: {
        label: "healthy",
        icon: Zap,
    },
    unhealthy: {
        label: "unhealthy",
        icon: ZapOff,
    },
    disabled: {
        label: "disabled",
        icon: PowerOff,
    },
    none: {
        label: "none",
        icon: null,
    },
} as Record<string, StatusType>;

export const NodeSchema = z.object({
    name: z.string().min(1),
    address: z.string().min(1),
    port: z
        .number()
        .min(1)
        .or(z.string().transform((v) => Number.parseFloat(v))),
    id: z.number().nullable().optional(),
    status: z.enum([
        NodesStatus.healthy.label,
        NodesStatus.unhealthy.label,
        "none",
        NodesStatus.disabled.label,
    ]),
    usage_coefficient: z
        .number()
        .default(1.0)
        .or(z.string().transform((v) => Number.parseFloat(v))),
    connection_backend: z.enum(["grpclib", "grpcio"]).default("grpclib"),
});

export type NodeBackendType = {
    name: string;
    backend_type: string;
    version: string;
    running: boolean;
};

export type NodeType = z.infer<typeof NodeSchema> & {
    id: number;
    backends: NodeBackendType[];
    message?: string | null;
    adblock_enabled?: boolean;
    address_in_hosts?: boolean;
};

export const DnsProviders = {
    adguard_home_local: "AdGuard Home (local)",
    adguard_dns_public: "AdGuard DNS (public)",
    nextdns: "NextDNS",
    cloudflare_security: "Cloudflare Security",
    custom: "Custom",
} as const;

export type DnsProvider = keyof typeof DnsProviders;

export type NodeFilteringConfig = {
    adblock_enabled: boolean;
    dns_provider: DnsProvider;
    dns_address: string | null;
    adguard_home_port: number;
    adguard_home_installed: boolean;
};

export type SSHCredentialsInfo = {
    exists: boolean;
    ssh_user?: string | null;
    ssh_port?: number | null;
};

export type DeviceInfo = {
    remote_ip: string;
    client_name: string;
    user_agent?: string | null;
    protocol?: string | null;
    tls_fingerprint?: string | null;
    first_seen: number;
    last_seen: number;
    total_usage: number;
    uplink: number;
    downlink: number;
    is_active: boolean;
};

export type DeviceInfoWithUser = DeviceInfo & { uid: number };

export type UserDevicesResponse = {
    uid: number;
    devices: DeviceInfo[];
};

export type AllUsersDevicesResponse = {
    users: UserDevicesResponse[];
};
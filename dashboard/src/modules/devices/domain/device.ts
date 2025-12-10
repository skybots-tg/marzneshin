export interface DeviceType {
    id: number;
    user_id: number;
    fingerprint: string;
    fingerprint_version: number;
    display_name?: string | null;
    client_name?: string | null;
    client_type: string;
    first_seen_at: string | Date;
    last_seen_at: string | Date;
    last_node_id?: number | null;
    is_blocked: boolean;
    trust_level: number;
    total_upload_bytes?: number;
    total_download_bytes?: number;
    total_connect_count?: number;
    ip_count?: number;
}

export interface DeviceIPType {
    id: number;
    ip: string;
    first_seen_at: string | Date;
    last_seen_at: string | Date;
    connect_count: number;
    upload_bytes: number;
    download_bytes: number;
    country_code?: string | null;
    asn?: number | null;
    asn_org?: string | null;
    region?: string | null;
    city?: string | null;
    is_datacenter?: boolean | null;
}

export interface DeviceDetailType extends DeviceType {
    last_ip?: DeviceIPType | null;
    ips: DeviceIPType[];
}

export interface DeviceStatisticsType {
    user_id: number;
    total_devices: number;
    active_devices: number;
    blocked_devices: number;
    total_ips: number;
    unique_countries: string[];
    total_traffic: number;
    suspicious_devices?: number;
}


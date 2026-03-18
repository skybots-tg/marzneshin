import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";

export interface DatabasePoolStats {
    pool_size: number;
    max_overflow: number;
    pool_timeout: number;
    pool_recycle: number;
    statement_timeout: number;
    connect_timeout: number;
    checked_out: number;
    checked_in: number;
    overflow: number;
    total_connections: number;
    max_connections: number;
}

export async function fetchDatabaseSettings(): Promise<DatabasePoolStats> {
    return fetch(`/system/settings/database`);
}

export const databaseSettingsQueryKey = ["system", "settings", "database"];

export const useDatabaseSettingsQuery = () => {
    return useQuery({
        queryKey: databaseSettingsQueryKey,
        queryFn: fetchDatabaseSettings,
        refetchInterval: 5000,
    });
};

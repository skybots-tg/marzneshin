import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";
import {
    databaseSettingsQueryKey,
    type DatabasePoolStats,
} from "./database-settings.query";

export interface DatabasePoolConfig {
    pool_size: number;
    max_overflow: number;
    pool_timeout: number;
    pool_recycle: number;
}

export async function updateDatabaseSettings(
    config: DatabasePoolConfig
): Promise<DatabasePoolStats> {
    return fetch("/system/settings/database", {
        method: "put",
        body: config,
    });
}

const handleError = () => {
    toast.error(i18n.t("events.update.error"));
};

const handleSuccess = () => {
    toast.success(
        i18n.t("events.update.success.title", {
            name: i18n.t("page.settings.database.title"),
        }),
        { description: i18n.t("events.update.success.desc") }
    );
    queryClient.invalidateQueries({ queryKey: databaseSettingsQueryKey });
};

export const useDatabaseSettingsMutation = () => {
    return useMutation({
        mutationKey: databaseSettingsQueryKey,
        mutationFn: updateDatabaseSettings,
        onError: handleError,
        onSuccess: handleSuccess,
    });
};

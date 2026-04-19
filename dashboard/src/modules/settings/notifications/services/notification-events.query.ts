import { useQuery } from "@tanstack/react-query";
import { fetch } from "@marzneshin/common/utils";

export type NotificationEventKey =
    | "user_created"
    | "user_updated"
    | "user_activated"
    | "user_deactivated"
    | "user_deleted"
    | "user_enabled"
    | "user_disabled"
    | "data_usage_reset"
    | "subscription_revoked"
    | "reached_usage_percent"
    | "reached_days_left"
    | "data_limit_exhausted";

export type NotificationEventsSettings = Record<NotificationEventKey, boolean>;

export const NOTIFICATION_EVENT_KEYS: NotificationEventKey[] = [
    "user_created",
    "user_updated",
    "user_activated",
    "user_deactivated",
    "user_deleted",
    "user_enabled",
    "user_disabled",
    "data_usage_reset",
    "subscription_revoked",
    "reached_usage_percent",
    "reached_days_left",
    "data_limit_exhausted",
];

export const DEFAULT_NOTIFICATION_EVENTS: NotificationEventsSettings = {
    user_created: true,
    user_updated: true,
    user_activated: true,
    user_deactivated: true,
    user_deleted: true,
    user_enabled: true,
    user_disabled: true,
    data_usage_reset: true,
    subscription_revoked: true,
    reached_usage_percent: true,
    reached_days_left: true,
    data_limit_exhausted: true,
};

export async function fetchNotificationEventsSettings(): Promise<NotificationEventsSettings> {
    return fetch(`/system/settings/notification-events`);
}

export const notificationEventsQueryKey = [
    "system",
    "settings",
    "notification-events",
];

export const useNotificationEventsQuery = () => {
    return useQuery({
        queryKey: notificationEventsQueryKey,
        queryFn: fetchNotificationEventsSettings,
        initialData: DEFAULT_NOTIFICATION_EVENTS,
    });
};

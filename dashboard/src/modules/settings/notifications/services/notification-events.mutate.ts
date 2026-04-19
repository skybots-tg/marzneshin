import { useMutation } from "@tanstack/react-query";
import { fetch, queryClient } from "@marzneshin/common/utils";
import { toast } from "sonner";
import i18n from "@marzneshin/features/i18n";
import {
    notificationEventsQueryKey,
    type NotificationEventsSettings,
} from "./notification-events.query";

export async function updateNotificationEventsSettings(
    payload: NotificationEventsSettings,
): Promise<NotificationEventsSettings> {
    return fetch("/system/settings/notification-events", {
        method: "put",
        body: payload,
    });
}

const handleError = () => {
    toast.error(i18n.t("events.update.error"));
};

const handleSuccess = () => {
    toast.success(
        i18n.t("events.update.success.title", {
            name: i18n.t("page.settings.notifications.title"),
        }),
        { description: i18n.t("events.update.success.desc") },
    );
    queryClient.invalidateQueries({ queryKey: notificationEventsQueryKey });
};

export const useNotificationEventsMutation = () => {
    return useMutation({
        mutationKey: notificationEventsQueryKey,
        mutationFn: updateNotificationEventsSettings,
        onError: handleError,
        onSuccess: handleSuccess,
    });
};

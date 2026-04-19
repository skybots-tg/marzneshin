import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
    SectionWidget,
    Switch,
    Button,
    HStack,
    Separator,
    Label,
} from "@marzneshin/common/components";
import {
    useNotificationEventsQuery,
    useNotificationEventsMutation,
    DEFAULT_NOTIFICATION_EVENTS,
    NOTIFICATION_EVENT_KEYS,
    type NotificationEventKey,
    type NotificationEventsSettings,
} from "../services";

interface EventGroup {
    titleKey: string;
    descKey: string;
    events: NotificationEventKey[];
}

const EVENT_GROUPS: EventGroup[] = [
    {
        titleKey: "page.settings.notifications.groups.lifecycle.title",
        descKey: "page.settings.notifications.groups.lifecycle.desc",
        events: [
            "user_created",
            "user_updated",
            "user_deleted",
            "user_enabled",
            "user_disabled",
        ],
    },
    {
        titleKey: "page.settings.notifications.groups.status.title",
        descKey: "page.settings.notifications.groups.status.desc",
        events: ["user_activated", "user_deactivated"],
    },
    {
        titleKey: "page.settings.notifications.groups.warnings.title",
        descKey: "page.settings.notifications.groups.warnings.desc",
        events: [
            "reached_usage_percent",
            "reached_days_left",
            "data_limit_exhausted",
        ],
    },
    {
        titleKey: "page.settings.notifications.groups.reset.title",
        descKey: "page.settings.notifications.groups.reset.desc",
        events: ["data_usage_reset", "subscription_revoked"],
    },
];

const settingsEqual = (
    a: NotificationEventsSettings,
    b: NotificationEventsSettings,
): boolean => NOTIFICATION_EVENT_KEYS.every((key) => a[key] === b[key]);

export const NotificationEventsWidget = () => {
    const { t } = useTranslation();
    const { data, isFetching } = useNotificationEventsQuery();
    const mutation = useNotificationEventsMutation();

    const serverState = useMemo<NotificationEventsSettings>(
        () => ({ ...DEFAULT_NOTIFICATION_EVENTS, ...(data ?? {}) }),
        [data],
    );

    const [draft, setDraft] = useState<NotificationEventsSettings>(serverState);

    useEffect(() => {
        setDraft(serverState);
    }, [serverState]);

    const isDirty = !settingsEqual(draft, serverState);
    const isLoading = isFetching && !data;

    const handleToggle = (key: NotificationEventKey, value: boolean) => {
        setDraft((prev) => ({ ...prev, [key]: value }));
    };

    const handleGroupToggle = (group: EventGroup, value: boolean) => {
        setDraft((prev) => {
            const next = { ...prev };
            for (const key of group.events) {
                next[key] = value;
            }
            return next;
        });
    };

    const handleReset = () => setDraft(serverState);
    const handleSave = () => mutation.mutate(draft);

    const tn = (key: string) => t(`page.settings.notifications.${key}`);
    const tEvent = (key: NotificationEventKey) => tn(`events.${key}.label`);
    const tEventDesc = (key: NotificationEventKey) => tn(`events.${key}.desc`);

    const enabledCount = NOTIFICATION_EVENT_KEYS.filter(
        (key) => draft[key],
    ).length;

    return (
        <SectionWidget
            title={
                <HStack className="items-center gap-2">
                    <span>{tn("title")}</span>
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium tabular-nums text-muted-foreground">
                        {enabledCount}/{NOTIFICATION_EVENT_KEYS.length}
                    </span>
                </HStack>
            }
            description={tn("description")}
            content={
                <div className="flex flex-col gap-4 w-full max-w-4xl">
                    {isLoading ? (
                        <div className="flex flex-col gap-3 animate-pulse">
                            {Array.from({ length: 4 }).map((_, i) => (
                                <div
                                    key={i}
                                    className="h-16 rounded-lg bg-secondary/40"
                                />
                            ))}
                        </div>
                    ) : (
                        EVENT_GROUPS.map((group, idx) => {
                            const groupAllOn = group.events.every(
                                (k) => draft[k],
                            );
                            return (
                                <div
                                    key={group.titleKey}
                                    className="flex flex-col gap-3"
                                >
                                    {idx > 0 && <Separator />}
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="flex flex-col gap-0.5">
                                            <Label className="text-sm font-semibold">
                                                {t(group.titleKey)}
                                            </Label>
                                            <p className="text-xs text-muted-foreground">
                                                {t(group.descKey)}
                                            </p>
                                        </div>
                                        <Switch
                                            checked={groupAllOn}
                                            onCheckedChange={(v) =>
                                                handleGroupToggle(group, v)
                                            }
                                            aria-label={t(group.titleKey)}
                                        />
                                    </div>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                        {group.events.map((key) => (
                                            <label
                                                key={key}
                                                htmlFor={`notif-${key}`}
                                                className="flex items-start justify-between gap-3 rounded-lg border border-border/40 bg-secondary/20 px-3 py-2.5 cursor-pointer hover:bg-secondary/40 transition-colors"
                                            >
                                                <div className="flex flex-col gap-0.5 min-w-0">
                                                    <span className="text-sm font-medium truncate">
                                                        {tEvent(key)}
                                                    </span>
                                                    <span className="text-xs text-muted-foreground line-clamp-2">
                                                        {tEventDesc(key)}
                                                    </span>
                                                </div>
                                                <Switch
                                                    id={`notif-${key}`}
                                                    checked={draft[key]}
                                                    onCheckedChange={(v) =>
                                                        handleToggle(key, v)
                                                    }
                                                />
                                            </label>
                                        ))}
                                    </div>
                                </div>
                            );
                        })
                    )}

                    <p className="text-xs text-muted-foreground">
                        {tn("hint")}
                    </p>

                    <HStack className="w-full justify-end gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            className="w-fit"
                            onClick={handleReset}
                            disabled={!isDirty || mutation.isPending}
                        >
                            {t(
                                "page.settings.subscription-settings.reset-local-changes",
                            )}
                        </Button>
                        <Button
                            type="button"
                            className="w-fit"
                            onClick={handleSave}
                            disabled={!isDirty || mutation.isPending}
                        >
                            {t("apply")}
                        </Button>
                    </HStack>
                </div>
            }
        />
    );
};

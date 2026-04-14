import { useEffect, useCallback, useMemo } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import {
    SectionWidget,
    Form,
    FormField,
    FormItem,
    FormLabel,
    FormControl,
    FormDescription,
    Input,
    Button,
    HStack,
    Separator,
    Badge,
} from "@marzneshin/common/components";
import {
    useDatabaseSettingsQuery,
    useDatabaseSettingsMutation,
    type DatabasePoolConfig,
} from "@marzneshin/modules/settings/database";

function PoolGauge({
    used,
    max,
    label,
}: {
    used: number;
    max: number;
    label: string;
}) {
    const pct = max > 0 ? Math.round((used / max) * 100) : 0;
    const variant =
        pct >= 90 ? "destructive" : pct >= 70 ? "secondary" : "default";

    return (
        <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-muted-foreground">{label}</span>
            <div className="flex items-center gap-2">
                <div className="w-24 h-2 rounded-full bg-muted overflow-hidden">
                    <div
                        className={`h-full rounded-full transition-all ${
                            pct >= 90
                                ? "bg-destructive"
                                : pct >= 70
                                  ? "bg-yellow-500"
                                  : "bg-primary"
                        }`}
                        style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                </div>
                <Badge variant={variant} className="text-xs tabular-nums">
                    {used}/{max}
                </Badge>
            </div>
        </div>
    );
}

export const DatabaseSettingsWidget = () => {
    const { t } = useTranslation();
    const { data, isFetching } = useDatabaseSettingsQuery();
    const mutation = useDatabaseSettingsMutation();

    const defaults = useMemo(
        () => ({
            pool_size: data?.pool_size ?? 20,
            max_overflow: data?.max_overflow ?? 10,
            pool_timeout: data?.pool_timeout ?? 30,
            pool_recycle: data?.pool_recycle ?? 1800,
        }),
        [data]
    );

    const form = useForm<DatabasePoolConfig>({ defaultValues: defaults });

    const syncFromServer = useCallback(() => {
        if (data) form.reset(defaults, { keepDirtyValues: true });
    }, [data, defaults, form]);

    useEffect(() => {
        syncFromServer();
    }, [syncFromServer]);

    const onSubmit = (values: DatabasePoolConfig) => mutation.mutate(values);

    const tdb = (key: string) => t(`page.settings.database.${key}`);

    return (
        <SectionWidget
            title={tdb("title")}
            description={tdb("description")}
            content={
                <div className="flex flex-col gap-4 w-full max-w-4xl">
                    {/* Live stats */}
                    <div className="rounded-lg border p-4 space-y-3">
                        <h4 className="text-sm font-medium">
                            {tdb("live-stats")}
                        </h4>
                        {data && (
                            <>
                                <PoolGauge
                                    used={data.checked_out}
                                    max={data.max_connections}
                                    label={tdb("active-connections")}
                                />
                                <PoolGauge
                                    used={data.total_connections}
                                    max={data.max_connections}
                                    label={tdb("total-connections")}
                                />
                                <PoolGauge
                                    used={data.overflow}
                                    max={data.max_overflow}
                                    label={tdb("overflow")}
                                />
                                <PoolGauge
                                    used={data.checked_in}
                                    max={data.pool_size}
                                    label={tdb("idle")}
                                />
                            </>
                        )}
                        {isFetching && !data && (
                            <p className="text-sm text-muted-foreground">
                                {t("loading")}...
                            </p>
                        )}
                    </div>

                    <Separator />

                    {/* Editable pool settings */}
                    <Form {...form}>
                        <form
                            onSubmit={form.handleSubmit(onSubmit)}
                            className="flex flex-col gap-3"
                        >
                            <div className="grid grid-cols-2 gap-3">
                                <FormField
                                    control={form.control}
                                    name="pool_size"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>
                                                {tdb("pool-size")}
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    className="h-8"
                                                    type="number"
                                                    min={1}
                                                    max={200}
                                                    {...field}
                                                    onChange={(e) =>
                                                        field.onChange(
                                                            Number(
                                                                e.target.value
                                                            )
                                                        )
                                                    }
                                                />
                                            </FormControl>
                                            <FormDescription>
                                                {tdb("pool-size-desc")}
                                            </FormDescription>
                                        </FormItem>
                                    )}
                                />
                                <FormField
                                    control={form.control}
                                    name="max_overflow"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>
                                                {tdb("max-overflow")}
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    className="h-8"
                                                    type="number"
                                                    min={0}
                                                    max={200}
                                                    {...field}
                                                    onChange={(e) =>
                                                        field.onChange(
                                                            Number(
                                                                e.target.value
                                                            )
                                                        )
                                                    }
                                                />
                                            </FormControl>
                                            <FormDescription>
                                                {tdb("max-overflow-desc")}
                                            </FormDescription>
                                        </FormItem>
                                    )}
                                />
                                <FormField
                                    control={form.control}
                                    name="pool_timeout"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>
                                                {tdb("pool-timeout")}
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    className="h-8"
                                                    type="number"
                                                    min={1}
                                                    max={300}
                                                    {...field}
                                                    onChange={(e) =>
                                                        field.onChange(
                                                            Number(
                                                                e.target.value
                                                            )
                                                        )
                                                    }
                                                />
                                            </FormControl>
                                            <FormDescription>
                                                {tdb("pool-timeout-desc")}
                                            </FormDescription>
                                        </FormItem>
                                    )}
                                />
                                <FormField
                                    control={form.control}
                                    name="pool_recycle"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>
                                                {tdb("pool-recycle")}
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    className="h-8"
                                                    type="number"
                                                    min={60}
                                                    max={7200}
                                                    {...field}
                                                    onChange={(e) =>
                                                        field.onChange(
                                                            Number(
                                                                e.target.value
                                                            )
                                                        )
                                                    }
                                                />
                                            </FormControl>
                                            <FormDescription>
                                                {tdb("pool-recycle-desc")}
                                            </FormDescription>
                                        </FormItem>
                                    )}
                                />
                            </div>
                            <p className="text-xs text-muted-foreground">
                                {tdb("restart-note")}
                            </p>
                            <HStack className="w-full flex-end">
                                <Button
                                    type="button"
                                    variant="outline"
                                    className="w-fit"
                                    onClick={() => form.reset(defaults)}
                                >
                                    {t(
                                        "page.settings.subscription-settings.reset-local-changes"
                                    )}
                                </Button>
                                <Button
                                    type="submit"
                                    className="w-fit"
                                    disabled={mutation.isPending}
                                >
                                    {t("apply")}
                                </Button>
                            </HStack>
                        </form>
                    </Form>
                </div>
            }
        />
    );
};

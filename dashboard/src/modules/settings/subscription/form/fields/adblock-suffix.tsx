import {
    FormField,
    FormItem,
    FormLabel,
    Input,
    FormControl,
    FormDescription,
    CheckboxField,
} from "@marzneshin/common/components";
import { useFormContext, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";

export const AdblockSuffixField = () => {
    const { t } = useTranslation();
    const form = useFormContext();
    const enabled = useWatch({
        control: form.control,
        name: "host_remark_adblock_suffix_enabled",
    });

    return (
        <div className="flex flex-col gap-2">
            <CheckboxField
                name="host_remark_adblock_suffix_enabled"
                label={t(
                    "page.settings.subscription-settings.adblock-suffix-enabled",
                )}
            />
            <FormField
                control={form.control}
                name="host_remark_adblock_suffix_text"
                render={({ field }) => (
                    <FormItem>
                        <FormLabel>
                            {t(
                                "page.settings.subscription-settings.adblock-suffix-text",
                            )}
                        </FormLabel>
                        <FormControl>
                            <Input
                                className="h-8"
                                disabled={!enabled}
                                {...field}
                            />
                        </FormControl>
                        <FormDescription>
                            {t(
                                "page.settings.subscription-settings.adblock-suffix-desc",
                            )}
                        </FormDescription>
                    </FormItem>
                )}
            />
        </div>
    );
};

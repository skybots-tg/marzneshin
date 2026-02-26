import {
    Checkbox,
    FormControl,
    FormDescription,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
    Input,
} from "@marzneshin/common/components";
import { useFormContext } from "react-hook-form";
import { useTranslation } from "react-i18next";

export const MlkemFields = () => {
    const { t } = useTranslation();
    const form = useFormContext();
    const enabled = form.watch("mlkem_enabled");

    return (
        <div className="w-full flex flex-col gap-2">
            <FormField
                control={form.control}
                name="mlkem_enabled"
                render={({ field }) => (
                    <FormItem className="flex flex-row items-center space-x-2">
                        <FormControl>
                            <Checkbox
                                checked={field.value}
                                onCheckedChange={field.onChange}
                            />
                        </FormControl>
                        <FormLabel>
                            {t("page.hosts.mlkem-enabled")}
                        </FormLabel>
                        <FormMessage />
                    </FormItem>
                )}
            />
            {enabled && (
                <FormField
                    control={form.control}
                    name="mlkem_public_key"
                    render={({ field }) => (
                        <FormItem className="w-full">
                            <FormLabel>
                                {t("page.hosts.mlkem-public-key")}
                            </FormLabel>
                            <FormControl>
                                <Input {...field} readOnly />
                            </FormControl>
                            <FormDescription>
                                {t("page.hosts.mlkem-public-key-hint")}
                            </FormDescription>
                            <FormMessage />
                        </FormItem>
                    )}
                />
            )}
        </div>
    );
};



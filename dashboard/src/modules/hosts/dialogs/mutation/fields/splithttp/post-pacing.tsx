import {
    FormControl,
    FormField,
    FormItem,
    FormLabel,
    Input,
} from "@marzneshin/common/components";
import { useTranslation } from "react-i18next";

// Клиентский темп packet-up: без него шлюзы, которые банят IP за частые
// запросы, отрезают всех за одним мобильным адресом.
const PACING_FIELDS = [
    { name: "sc_min_posts_interval_ms", label: "xhttp_post_interval", placeholder: "100-200" },
    { name: "sc_max_each_post_bytes", label: "xhttp_post_bytes", placeholder: "1000000" },
];

export const SplitHttpPostPacingFields = (
    { updater }: { updater: (field: string, value: any) => void }
) => {
    const { t } = useTranslation();
    return (
        <>
            {PACING_FIELDS.map(({ name, label, placeholder }) => (
                <FormField
                    key={name}
                    name={`splithttp_settings.${name}`}
                    render={({ field }) => (
                        <FormItem>
                            <FormLabel>{t(label)}</FormLabel>
                            <FormControl>
                                <Input
                                    value={field.value ?? ""}
                                    placeholder={placeholder}
                                    onChange={(e) =>
                                        updater(
                                            `splithttp_settings.${name}`,
                                            e.target.value
                                        )
                                    }
                                    className="w-full"
                                />
                            </FormControl>
                        </FormItem>
                    )}
                />
            ))}
        </>
    )
}

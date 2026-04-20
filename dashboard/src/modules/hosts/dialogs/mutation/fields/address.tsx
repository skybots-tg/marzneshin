import {
    Badge,
    FormControl,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from "@marzneshin/common/components";
import { cn } from "@marzneshin/common/utils";
import { X } from "lucide-react";
import {
    type ChangeEvent,
    type KeyboardEvent,
    useRef,
    useState,
} from "react";
import {
    type ControllerRenderProps,
    type FieldValues,
    useFormContext,
} from "react-hook-form";
import { useTranslation } from "react-i18next";

const splitAddresses = (raw: string): string[] =>
    raw
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean);

const joinAddresses = (addresses: string[]): string => addresses.join(",");

interface AddressTagsInputProps {
    field: ControllerRenderProps<FieldValues, "address">;
}

const AddressTagsInput = ({ field }: AddressTagsInputProps) => {
    const { t } = useTranslation();
    const inputRef = useRef<HTMLInputElement>(null);
    const [draft, setDraft] = useState("");

    const rawValue = typeof field.value === "string" ? field.value : "";
    const addresses = splitAddresses(rawValue);

    const writeAddresses = (next: string[]) => {
        field.onChange(joinAddresses(next));
    };

    const addAddress = (candidate: string) => {
        const trimmed = candidate.trim();
        if (!trimmed) return;
        if (addresses.includes(trimmed)) return;
        writeAddresses([...addresses, trimmed]);
    };

    const removeAddress = (target: string) => {
        writeAddresses(addresses.filter((addr) => addr !== target));
        inputRef.current?.focus();
    };

    const commitDraft = () => {
        if (!draft.trim()) {
            setDraft("");
            return;
        }
        addAddress(draft);
        setDraft("");
    };

    const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value;
        if (!value.includes(",")) {
            setDraft(value);
            return;
        }
        const parts = value.split(",");
        const remainder = parts.pop() ?? "";
        const next = [...addresses];
        for (const part of parts) {
            const trimmed = part.trim();
            if (trimmed && !next.includes(trimmed)) next.push(trimmed);
        }
        writeAddresses(next);
        setDraft(remainder);
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault();
            commitDraft();
            return;
        }
        if (
            e.key === "Backspace" &&
            draft.length === 0 &&
            addresses.length > 0
        ) {
            e.preventDefault();
            const next = [...addresses];
            const last = next.pop() ?? "";
            writeAddresses(next);
            setDraft(last);
        }
    };

    return (
        <div
            role="presentation"
            onClick={() => inputRef.current?.focus()}
            className={cn(
                "flex flex-wrap items-center gap-1.5 min-h-10 w-full rounded-[10px] bg-secondary/60 px-2 py-1.5 text-left cursor-text",
                "border border-border/40",
                "focus-within:outline-none focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/40",
                "transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)]",
            )}
        >
            {addresses.map((addr) => (
                <Badge
                    key={addr}
                    variant="secondary"
                    className="gap-1 pl-2 pr-1 py-0.5 max-w-full"
                >
                    <span className="truncate font-mono text-xs">{addr}</span>
                    <button
                        type="button"
                        aria-label={t("remove")}
                        onClick={(e) => {
                            e.stopPropagation();
                            removeAddress(addr);
                        }}
                        className="rounded-full p-0.5 hover:bg-foreground/10 focus:outline-none focus:ring-1 focus:ring-ring/40"
                    >
                        <X className="size-3" />
                    </button>
                </Badge>
            ))}
            <input
                ref={inputRef}
                value={draft}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                onBlur={commitDraft}
                placeholder={
                    addresses.length === 0
                        ? t("page.hosts.address-placeholder")
                        : ""
                }
                className="flex-1 min-w-[80px] bg-transparent border-0 outline-none text-sm py-1 px-1.5"
            />
        </div>
    );
};

export const AddressField = () => {
    const { t } = useTranslation();
    const form = useFormContext();
    return (
        <FormField
            control={form.control}
            name="address"
            render={({ field }) => (
                <FormItem className="w-2/3">
                    <FormLabel>{t("address")}</FormLabel>
                    <FormControl>
                        <AddressTagsInput field={field} />
                    </FormControl>
                    <FormMessage />
                </FormItem>
            )}
        />
    );
};

import {
    Button,
    Label,
    MiniWidget,
} from "@marzneshin/common/components";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
    useSSHPinStatusQuery,
    useSetupSSHPinMutation,
    useDeleteSSHPinMutation,
} from "@marzneshin/modules/settings";
import { KeyRound, Trash2, ShieldCheck, ShieldAlert } from "lucide-react";
import { cn } from "@marzneshin/common/utils";

const PIN_LENGTH = 4;

const PinInput = ({
    value,
    onChange,
}: {
    value: string;
    onChange: (pin: string) => void;
}) => {
    const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
    const digits = value.padEnd(PIN_LENGTH, "").split("").slice(0, PIN_LENGTH);

    const focusAt = (index: number) => {
        inputRefs.current[index]?.focus();
    };

    const handleChange = (index: number, char: string) => {
        if (!/^\d?$/.test(char)) return;
        const next = digits.map((d, i) => (i === index ? char : d)).join("").trim();
        onChange(next);
        if (char && index < PIN_LENGTH - 1) {
            focusAt(index + 1);
        }
    };

    const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Backspace") {
            e.preventDefault();
            if (digits[index]) {
                handleChange(index, "");
            } else if (index > 0) {
                handleChange(index - 1, "");
                focusAt(index - 1);
            }
        } else if (e.key === "ArrowLeft" && index > 0) {
            focusAt(index - 1);
        } else if (e.key === "ArrowRight" && index < PIN_LENGTH - 1) {
            focusAt(index + 1);
        }
    };

    const handlePaste = (e: React.ClipboardEvent) => {
        e.preventDefault();
        const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, PIN_LENGTH);
        if (pasted) {
            onChange(pasted);
            focusAt(Math.min(pasted.length, PIN_LENGTH - 1));
        }
    };

    return (
        <div className="flex justify-center gap-3" onPaste={handlePaste}>
            {digits.map((digit, i) => (
                <input
                    key={i}
                    ref={(el) => { inputRefs.current[i] = el; }}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={1}
                    value={digit === " " ? "" : digit}
                    onChange={(e) => handleChange(i, e.target.value.slice(-1))}
                    onKeyDown={(e) => handleKeyDown(i, e)}
                    onFocus={(e) => e.target.select()}
                    className={cn(
                        "size-12 rounded-xl border-2 border-border/50 bg-secondary/40",
                        "text-center text-lg font-semibold",
                        "focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary/50",
                        "transition-all duration-200",
                        "placeholder:text-muted-foreground/30",
                    )}
                    placeholder="·"
                />
            ))}
        </div>
    );
};

export const SSHPinWidget = () => {
    const { t } = useTranslation();
    const { data: pinStatus } = useSSHPinStatusQuery();
    const setupMutation = useSetupSSHPinMutation();
    const deleteMutation = useDeleteSSHPinMutation();
    const [newPin, setNewPin] = useState("");

    const handleSetup = () => {
        setupMutation.mutate(newPin, {
            onSuccess: () => setNewPin(""),
        });
    };

    const handleDelete = () => {
        deleteMutation.mutate();
    };

    return (
        <MiniWidget title={t("page.settings.ssh_pin.title")}>
            <div className="space-y-3">
                {pinStatus.configured ? (
                    <div className="space-y-3">
                        <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
                            <ShieldCheck className="size-4" />
                            <span>{t("page.settings.ssh_pin.configured")}</span>
                        </div>
                        {pinStatus.has_credentials && (
                            <p className="text-xs text-muted-foreground">
                                {t("page.settings.ssh_pin.has_credentials_warning")}
                            </p>
                        )}
                        <Button
                            onClick={handleDelete}
                            variant="destructive"
                            size="sm"
                            className="w-full"
                            disabled={
                                pinStatus.has_credentials ||
                                deleteMutation.isPending
                            }
                        >
                            <Trash2 className="size-4 mr-2" />
                            {t("page.settings.ssh_pin.delete")}
                        </Button>
                    </div>
                ) : (
                    <div className="space-y-4">
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <ShieldAlert className="size-4" />
                            <span>{t("page.settings.ssh_pin.not_configured")}</span>
                        </div>
                        <div className="space-y-2">
                            <Label className="text-xs">
                                {t("page.settings.ssh_pin.enter_pin")}
                            </Label>
                            <PinInput value={newPin} onChange={setNewPin} />
                            <p className="text-xs text-muted-foreground text-center">
                                {t("page.settings.ssh_pin.pin_desc")}
                            </p>
                        </div>
                        <Button
                            onClick={handleSetup}
                            size="sm"
                            className="w-full"
                            disabled={
                                newPin.length !== PIN_LENGTH ||
                                setupMutation.isPending
                            }
                        >
                            <KeyRound className="size-4 mr-2" />
                            {t("page.settings.ssh_pin.setup")}
                        </Button>
                    </div>
                )}
            </div>
        </MiniWidget>
    );
};

import {
    Button,
    Input,
    Label,
    MiniWidget,
} from "@marzneshin/common/components";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
    useSSHPinStatusQuery,
    useSetupSSHPinMutation,
    useDeleteSSHPinMutation,
} from "@marzneshin/modules/settings";
import { KeyRound, Trash2, ShieldCheck, ShieldAlert } from "lucide-react";

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
                    <div className="space-y-3">
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <ShieldAlert className="size-4" />
                            <span>{t("page.settings.ssh_pin.not_configured")}</span>
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">
                                {t("page.settings.ssh_pin.enter_pin")}
                            </Label>
                            <Input
                                type="password"
                                maxLength={4}
                                placeholder="****"
                                value={newPin}
                                onChange={(e) =>
                                    setNewPin(
                                        e.target.value
                                            .replace(/\D/g, "")
                                            .slice(0, 4),
                                    )
                                }
                            />
                            <p className="text-xs text-muted-foreground">
                                {t("page.settings.ssh_pin.pin_desc")}
                            </p>
                        </div>
                        <Button
                            onClick={handleSetup}
                            size="sm"
                            className="w-full"
                            disabled={
                                newPin.length !== 4 ||
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

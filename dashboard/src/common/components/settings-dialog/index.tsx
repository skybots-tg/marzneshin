import { type FC, type PropsWithChildren, useEffect } from "react";
import {
    ScrollArea,
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from "@marzneshin/common/components";
import { useTranslation } from "react-i18next";

export interface SettingsDialogProps {
    onOpenChange: (state: boolean) => void;
    open: boolean;
    onClose?: () => void;
}

export const SettingsDialog: FC<SettingsDialogProps & PropsWithChildren> = ({
    open,
    onOpenChange,
    children,
    onClose = () => null,
}) => {
    const { t } = useTranslation();

    useEffect(() => {
        if (!open) onClose();
    }, [open, onClose]);

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="sm:min-w-full md:min-w-[60vw] lg:min-w-[50vw] max-w-[90vw] overflow-hidden flex flex-col gap-0 p-0">
                <SheetHeader className="px-6 pt-6 pb-4">
                    <SheetTitle>{t("settings")}</SheetTitle>
                </SheetHeader>
                <ScrollArea className="flex-1 min-h-0 px-6 pb-6">
                    <div className="flex flex-col gap-4 min-w-0">
                        {children}
                    </div>
                </ScrollArea>
            </SheetContent>
        </Sheet>
    );
};

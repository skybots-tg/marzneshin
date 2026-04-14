import type { FC } from "react";
import {
    Button,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    TooltipProvider,
} from "@marzneshin/common/components";
import { Copy, CopyPlus, Trash2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

interface BlockActionProps {
    onDuplicate?: () => void;
    onDelete?: () => void;
    duplicateTooltip?: string;
    deleteTooltip?: string;
    size?: "sm" | "icon";
}

export const BlockActions: FC<BlockActionProps> = ({
    onDuplicate,
    onDelete,
    duplicateTooltip,
    deleteTooltip,
    size = "icon",
}) => {
    const { t } = useTranslation();

    return (
        <TooltipProvider delayDuration={300}>
            <div className="flex items-center gap-0.5">
                {onDuplicate && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                variant="ghost"
                                size={size}
                                className="h-7 w-7"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onDuplicate();
                                }}
                            >
                                <CopyPlus className="size-3.5" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="top">
                            {duplicateTooltip ?? t("duplicate")}
                        </TooltipContent>
                    </Tooltip>
                )}
                {onDelete && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                variant="ghost"
                                size={size}
                                className="h-7 w-7 text-destructive hover:text-destructive"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onDelete();
                                }}
                            >
                                <Trash2 className="size-3.5" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="top">
                            {deleteTooltip ?? t("delete")}
                        </TooltipContent>
                    </Tooltip>
                )}
            </div>
        </TooltipProvider>
    );
};

interface CopyJsonButtonProps {
    getJson: () => string;
}

export const CopyJsonButton: FC<CopyJsonButtonProps> = ({ getJson }) => {
    const { t } = useTranslation();

    const handleCopy = () => {
        navigator.clipboard.writeText(getJson());
        toast.success("Copied to clipboard");
    };

    return (
        <TooltipProvider delayDuration={300}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                            e.stopPropagation();
                            handleCopy();
                        }}
                    >
                        <Copy className="size-3.5" />
                    </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                    {t("copy")} JSON
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};

interface AddButtonProps {
    onClick: () => void;
    label: string;
}

export const AddButton: FC<AddButtonProps> = ({ onClick, label }) => {
    return (
        <Button
            variant="outline"
            size="sm"
            className="w-full border-dashed gap-1.5"
            onClick={onClick}
        >
            <Plus className="size-3.5" />
            {label}
        </Button>
    );
};

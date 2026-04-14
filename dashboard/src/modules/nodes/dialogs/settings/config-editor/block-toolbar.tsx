import { type FC, useState } from "react";
import {
    Button,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Input,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@marzneshin/common/components";
import {
    ChevronsDownUp,
    ChevronsUpDown,
    Plus,
} from "lucide-react";
import { useTranslation } from "react-i18next";

interface BlockToolbarProps {
    onCollapseAll: () => void;
    onExpandAll: () => void;
    onAddSection: (key: string, type: "object" | "array") => void;
}

export const BlockToolbar: FC<BlockToolbarProps> = ({
    onCollapseAll,
    onExpandAll,
    onAddSection,
}) => {
    const { t } = useTranslation();
    const [newKey, setNewKey] = useState("");
    const [newType, setNewType] = useState<"object" | "array">("object");
    const [popoverOpen, setPopoverOpen] = useState(false);

    const handleAdd = () => {
        if (!newKey.trim()) return;
        onAddSection(newKey.trim(), newType);
        setNewKey("");
        setNewType("object");
        setPopoverOpen(false);
    };

    return (
        <div className="flex items-center gap-1.5">
            <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={onCollapseAll}
            >
                <ChevronsDownUp className="size-3" />
                {t("collapse")}
            </Button>
            <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={onExpandAll}
            >
                <ChevronsUpDown className="size-3" />
                {t("expand")}
            </Button>

            <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
                <PopoverTrigger asChild>
                    <Button variant="outline" size="sm" className="h-7 text-xs gap-1 ml-auto">
                        <Plus className="size-3" />
                        {t("add")}
                    </Button>
                </PopoverTrigger>
                <PopoverContent className="w-64 space-y-3" align="end">
                    <div className="space-y-1.5">
                        <Label className="text-xs">{t("name")}</Label>
                        <Input
                            value={newKey}
                            onChange={(e) => setNewKey(e.target.value)}
                            placeholder="e.g. dns, policy..."
                            className="h-8 text-sm"
                            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs">{t("type")}</Label>
                        <Select
                            value={newType}
                            onValueChange={(v) => setNewType(v as "object" | "array")}
                        >
                            <SelectTrigger className="h-8 text-sm">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="object">Object {"{}"}</SelectItem>
                                <SelectItem value="array">Array {"[]"}</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                    <Button size="sm" className="w-full h-8" onClick={handleAdd} disabled={!newKey.trim()}>
                        <Plus className="size-3 mr-1" />
                        {t("add")}
                    </Button>
                </PopoverContent>
            </Popover>
        </div>
    );
};

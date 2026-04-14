import { type FC, useState, useMemo, useCallback } from "react";
import {
    Card,
    CardContent,
    Badge,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@marzneshin/common/components";
import {
    SortableItem,
    SortableDragHandle,
} from "@marzneshin/common/components/ui/sortable";
import { GripVertical, ChevronRight } from "lucide-react";
import Editor from "@monaco-editor/react";
import { useTheme } from "@marzneshin/features/theme-switch";
import type { ConfigBlockItem } from "./types";
import { BlockActions } from "./block-actions";
import { cn } from "@marzneshin/common/utils";

interface ArrayItemBlockProps {
    item: ConfigBlockItem;
    index: number;
    onUpdate: (value: string) => void;
    onDuplicate: () => void;
    onRemove: () => void;
}

function extractSummary(jsonStr: string): string {
    try {
        const obj = JSON.parse(jsonStr);
        if (typeof obj !== "object" || obj === null) return "";
        const parts: string[] = [];
        if (obj.tag) parts.push(obj.tag);
        if (obj.protocol) parts.push(obj.protocol);
        if (obj.type) parts.push(obj.type);
        if (obj.port) parts.push(`port:${obj.port}`);
        if (obj.listen) parts.push(obj.listen);
        if (obj.outboundTag) parts.push(`→ ${obj.outboundTag}`);
        if (obj.outbound) parts.push(`→ ${obj.outbound}`);
        if (obj.server) parts.push(`→ ${obj.server}`);
        return parts.join("  ·  ");
    } catch {
        return "";
    }
}

export const ArrayItemBlock: FC<ArrayItemBlockProps> = ({
    item,
    index,
    onUpdate,
    onDuplicate,
    onRemove,
}) => {
    const { theme } = useTheme();
    const [open, setOpen] = useState(false);

    const summary = useMemo(() => extractSummary(item.value), [item.value]);
    const hasError = item.error !== null;

    const handleChange = useCallback(
        (val: string | undefined) => {
            if (val !== undefined) onUpdate(val);
        },
        [onUpdate]
    );

    return (
        <SortableItem value={item.id} asChild>
            <div>
                <Card
                    className={cn(
                        "transition-colors",
                        hasError && "border-destructive/50"
                    )}
                >
                    <Collapsible open={open} onOpenChange={setOpen}>
                        <CollapsibleTrigger className="w-full">
                            <div className="flex items-center gap-2 px-3 py-2">
                                <SortableDragHandle
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 cursor-grab shrink-0"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    <GripVertical className="size-3.5 text-muted-foreground" />
                                </SortableDragHandle>

                                <ChevronRight
                                    className={cn(
                                        "size-3.5 text-muted-foreground transition-transform shrink-0",
                                        open && "rotate-90"
                                    )}
                                />

                                <Badge
                                    variant="outline"
                                    className="text-[10px] font-mono shrink-0 tabular-nums"
                                >
                                    {index}
                                </Badge>

                                {summary && (
                                    <span className="text-xs text-muted-foreground truncate text-left">
                                        {summary}
                                    </span>
                                )}

                                {hasError && (
                                    <Badge variant="destructive" className="text-[10px] ml-auto shrink-0">
                                        error
                                    </Badge>
                                )}

                                <div className="ml-auto shrink-0">
                                    <BlockActions
                                        onCopy={onDuplicate}
                                        onDelete={onRemove}
                                    />
                                </div>
                            </div>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                            <CardContent className="p-2 pt-0">
                                <Editor
                                    height="150px"
                                    language="json"
                                    theme={theme === "dark" ? "vs-dark" : "light"}
                                    value={item.value}
                                    onChange={handleChange}
                                    options={{
                                        minimap: { enabled: false },
                                        lineNumbers: "off",
                                        glyphMargin: false,
                                        folding: true,
                                        scrollBeyondLastLine: false,
                                        fontSize: 12,
                                        tabSize: 2,
                                        automaticLayout: true,
                                        wordWrap: "on",
                                        padding: { top: 8, bottom: 8 },
                                        renderLineHighlight: "none",
                                        overviewRulerLanes: 0,
                                        hideCursorInOverviewRuler: true,
                                        scrollbar: {
                                            vertical: "auto",
                                            horizontal: "hidden",
                                            verticalScrollbarSize: 6,
                                        },
                                    }}
                                />
                            </CardContent>
                        </CollapsibleContent>
                    </Collapsible>
                </Card>
            </div>
        </SortableItem>
    );
};

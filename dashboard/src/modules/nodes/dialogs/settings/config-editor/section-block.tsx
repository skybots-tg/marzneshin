import { type FC, useCallback } from "react";
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Badge,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@marzneshin/common/components";
import {
    ChevronRight,
    ScrollText,
    Globe,
    Route,
    Server,
    ArrowUpDown,
    Shield,
    BarChart3,
    Settings,
    Zap,
    FileJson,
    type LucideIcon,
} from "lucide-react";
import Editor from "@monaco-editor/react";
import { useTheme } from "@marzneshin/features/theme-switch";
import type { ConfigBlock, ConfigBlockItem } from "./types";
import { BlockActions, CopyJsonButton } from "./block-actions";
import { ArrayBlock } from "./array-block";
import { cn } from "@marzneshin/common/utils";

const SECTION_ICONS: Record<string, LucideIcon> = {
    log: ScrollText,
    dns: Globe,
    routing: Route,
    route: Route,
    inbounds: Server,
    outbounds: ArrowUpDown,
    policy: Shield,
    stats: BarChart3,
    api: Zap,
    experimental: Settings,
};

interface SectionBlockProps {
    block: ConfigBlock;
    onToggleCollapse: () => void;
    onDuplicate: () => void;
    onRemove: () => void;
    onUpdateRaw: (value: string) => void;
    onUpdateItem: (itemId: string | number, value: string) => void;
    onDuplicateItem: (itemId: string | number) => void;
    onRemoveItem: (itemId: string | number) => void;
    onReorderItems: (newItems: ConfigBlockItem[]) => void;
    onAddItem: () => void;
}

export const SectionBlock: FC<SectionBlockProps> = ({
    block,
    onToggleCollapse,
    onDuplicate,
    onRemove,
    onUpdateRaw,
    onUpdateItem,
    onDuplicateItem,
    onRemoveItem,
    onReorderItems,
    onAddItem,
}) => {
    const { theme } = useTheme();
    const Icon = SECTION_ICONS[block.key] ?? FileJson;
    const hasError = block.error !== null;

    const handleChange = useCallback(
        (val: string | undefined) => {
            if (val !== undefined) onUpdateRaw(val);
        },
        [onUpdateRaw]
    );

    const getJson = useCallback(() => {
        if (block.type === "array") {
            const items = block.items.map((i) => {
                try { return JSON.parse(i.value); }
                catch { return null; }
            });
            return JSON.stringify({ [block.key]: items }, null, 2);
        }
        try {
            return JSON.stringify(
                { [block.key]: JSON.parse(block.rawValue) },
                null,
                2
            );
        } catch {
            return block.rawValue;
        }
    }, [block]);

    return (
        <Card
            className={cn(
                "transition-colors",
                hasError && "border-destructive/50"
            )}
        >
            <Collapsible
                open={!block.collapsed}
                onOpenChange={() => onToggleCollapse()}
            >
                <CollapsibleTrigger className="w-full">
                    <CardHeader className="flex flex-row items-center gap-2 py-3 px-4">
                        <ChevronRight
                            className={cn(
                                "size-4 text-muted-foreground transition-transform shrink-0",
                                !block.collapsed && "rotate-90"
                            )}
                        />
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <CardTitle className="text-sm font-medium">
                            {block.key}
                        </CardTitle>

                        {block.type === "array" && (
                            <Badge variant="outline" className="text-[10px] tabular-nums shrink-0">
                                {block.items.length}
                            </Badge>
                        )}

                        {hasError && (
                            <Badge variant="destructive" className="text-[10px] shrink-0">
                                {block.type === "array"
                                    ? `${block.items.filter((i) => i.error).length} err`
                                    : "error"}
                            </Badge>
                        )}

                        <div className="ml-auto flex items-center gap-0.5 shrink-0">
                            <CopyJsonButton getJson={getJson} />
                            <BlockActions
                                onCopy={onDuplicate}
                                onDelete={onRemove}
                            />
                        </div>
                    </CardHeader>
                </CollapsibleTrigger>
                <CollapsibleContent>
                    <CardContent className="px-4 pb-4 pt-0">
                        {block.type === "array" ? (
                            <ArrayBlock
                                block={block}
                                onUpdateItem={onUpdateItem}
                                onDuplicateItem={onDuplicateItem}
                                onRemoveItem={onRemoveItem}
                                onReorder={onReorderItems}
                                onAddItem={onAddItem}
                            />
                        ) : (
                            <Editor
                                height="200px"
                                language="json"
                                theme={theme === "dark" ? "vs-dark" : "light"}
                                value={block.rawValue}
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
                        )}
                    </CardContent>
                </CollapsibleContent>
            </Collapsible>
        </Card>
    );
};

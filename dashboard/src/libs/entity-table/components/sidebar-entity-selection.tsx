import { useMemo, useState } from "react";
import {
    ScrollArea, Button, Badge, Input,
    Collapsible, CollapsibleContent, CollapsibleTrigger,
} from "@marzneshin/common/components";
import { cn } from "@marzneshin/common/utils";
import {
    useSidebarEntityTableContext
} from "@marzneshin/libs/entity-table/contexts";
import { useTranslation } from "react-i18next";
import { ChevronRight, Search, X, Layers } from "lucide-react";

interface InboundLike {
    id: number | string;
    tag?: string;
    protocol?: string;
    node?: { name?: string };
}

export const SidebarEntitySelection = () => {
    const {
        sidebarEntityId,
        sidebarEntities,
        setSidebarEntityId,
    } = useSidebarEntityTableContext();
    const { t } = useTranslation();

    const [search, setSearch] = useState("");
    const [manualCollapse, setManualCollapse] = useState<Record<string, boolean>>({});

    const entities = sidebarEntities as InboundLike[];
    const q = search.trim().toLowerCase();

    const selectedNodeName = useMemo(() => {
        const sel = entities.find((e) => String(e.id) === String(sidebarEntityId));
        return sel?.node?.name;
    }, [entities, sidebarEntityId]);

    const groups = useMemo(() => {
        const map = new Map<string, InboundLike[]>();
        for (const e of entities) {
            const nodeName = e.node?.name ?? "—";
            if (q) {
                const hay = `${e.tag ?? ""} ${nodeName} ${e.protocol ?? ""}`.toLowerCase();
                if (!hay.includes(q)) continue;
            }
            if (!map.has(nodeName)) map.set(nodeName, []);
            map.get(nodeName)!.push(e);
        }
        return Array.from(map.entries());
    }, [entities, q]);

    const totalMatches = useMemo(
        () => groups.reduce((acc, [, items]) => acc + items.length, 0),
        [groups],
    );

    const isOpen = (nodeName: string) => {
        if (q) return true; // expand everything while searching
        if (nodeName in manualCollapse) return !manualCollapse[nodeName];
        return nodeName === selectedNodeName; // collapsed by default, except the selected node's group
    };

    const toggleNode = (nodeName: string) => {
        setManualCollapse((prev) => ({
            ...prev,
            [nodeName]: nodeName in prev ? !prev[nodeName] : nodeName === selectedNodeName,
        }));
    };

    return (
        <div className="flex flex-col h-full min-h-[55vh]">
            <div className="flex flex-col gap-2 p-2 border-b sticky top-0 bg-background z-10">
                <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                    <Input
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder={t("page.hosts.inbound-search", "Search inbound / node…")}
                        className="h-9 pl-8 pr-8"
                    />
                    {search && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="absolute right-1 top-1/2 -translate-y-1/2 p-1 h-7 w-7"
                            onMouseDown={() => setSearch("")}
                        >
                            <X className="size-4" />
                        </Button>
                    )}
                </div>
                <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                        <Layers className="size-3.5" />
                        {t("inbounds")}: {totalMatches}
                    </span>
                    <Button
                        variant={sidebarEntityId ? "ghost" : "secondary"}
                        size="sm"
                        className="h-7 text-xs"
                        onMouseDown={() => setSidebarEntityId(undefined)}
                    >
                        {t("page.hosts.show-all", "All hosts")}
                    </Button>
                </div>
            </div>

            <ScrollArea className="flex-1 h-full">
                <div className="flex flex-col gap-1 p-2">
                    {groups.length === 0 && (
                        <div className="text-center text-sm text-muted-foreground py-8">
                            {t("no-results", "Nothing found")}
                        </div>
                    )}
                    {groups.map(([nodeName, items]) => {
                        const open = isOpen(nodeName);
                        const hasSelected = items.some((e) => String(e.id) === String(sidebarEntityId));
                        return (
                            <Collapsible key={nodeName} open={open}>
                                <CollapsibleTrigger asChild>
                                    <button
                                        type="button"
                                        onClick={() => toggleNode(nodeName)}
                                        className={cn(
                                            "w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left",
                                            "hover:bg-accent/60 transition-colors",
                                            hasSelected && "bg-accent/40",
                                        )}
                                    >
                                        <ChevronRight
                                            className={cn(
                                                "size-4 shrink-0 text-muted-foreground transition-transform",
                                                open && "rotate-90",
                                            )}
                                        />
                                        <span className="flex-1 truncate text-sm font-medium">{nodeName}</span>
                                        <Badge variant="secondary" className="h-5 px-1.5 text-[11px]">
                                            {items.length}
                                        </Badge>
                                    </button>
                                </CollapsibleTrigger>
                                <CollapsibleContent>
                                    <div className="flex flex-col gap-0.5 pl-4 pt-0.5">
                                        {items.map((entity) => {
                                            const active = String(entity.id) === String(sidebarEntityId);
                                            return (
                                                <button
                                                    type="button"
                                                    key={String(entity.id)}
                                                    onClick={() => setSidebarEntityId(String(entity.id))}
                                                    className={cn(
                                                        "w-full flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left",
                                                        "transition-colors",
                                                        active
                                                            ? "border-primary/60 bg-primary/10 dark:bg-primary/20"
                                                            : "border-transparent hover:bg-accent/60",
                                                    )}
                                                >
                                                    <span className={cn(
                                                        "flex-1 truncate text-sm",
                                                        active ? "font-medium" : "text-foreground/90",
                                                    )}>
                                                        {entity.tag}
                                                    </span>
                                                    {entity.protocol && (
                                                        <Badge
                                                            variant="outline"
                                                            className="h-5 px-1.5 text-[10px] uppercase shrink-0"
                                                        >
                                                            {entity.protocol}
                                                        </Badge>
                                                    )}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </CollapsibleContent>
                            </Collapsible>
                        );
                    })}
                </div>
            </ScrollArea>
        </div>
    );
};

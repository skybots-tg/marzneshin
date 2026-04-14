import { useState, useCallback, useRef } from "react";
import type { ConfigBlock, ConfigBlockItem } from "./types";

let blockIdCounter = 0;
const nextId = () => `block-${++blockIdCounter}`;
const nextItemId = () => `item-${++blockIdCounter}`;

function tryParseJson(str: string): Record<string, unknown> | null {
    try {
        const parsed = JSON.parse(str);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            return parsed;
        }
    } catch { /* ignore */ }
    return null;
}

function validateJson(str: string): string | null {
    try {
        JSON.parse(str);
        return null;
    } catch (e) {
        return e instanceof Error ? e.message : "Invalid JSON";
    }
}

function createBlockItems(arr: unknown[]): ConfigBlockItem[] {
    return arr.map((item) => {
        const value = JSON.stringify(item, null, 2);
        return { id: nextItemId(), value, error: null };
    });
}

function configToBlocks(configStr: string): ConfigBlock[] {
    const parsed = tryParseJson(configStr);
    if (!parsed) return [];

    return Object.entries(parsed).map(([key, value]) => {
        const isArray = Array.isArray(value);
        const rawValue = JSON.stringify(value, null, 2);

        return {
            id: nextId(),
            key,
            type: isArray ? "array" : "object",
            collapsed: false,
            error: null,
            rawValue,
            items: isArray ? createBlockItems(value) : [],
        } satisfies ConfigBlock;
    });
}

function blocksToConfig(blocks: ConfigBlock[]): string {
    const obj: Record<string, unknown> = {};

    for (const block of blocks) {
        if (block.type === "array") {
            const items: unknown[] = [];
            for (const item of block.items) {
                try {
                    items.push(JSON.parse(item.value));
                } catch {
                    items.push(null);
                }
            }
            obj[block.key] = items;
        } else {
            try {
                obj[block.key] = JSON.parse(block.rawValue);
            } catch {
                obj[block.key] = null;
            }
        }
    }

    return JSON.stringify(obj, null, 4);
}

function validateBlocks(blocks: ConfigBlock[]): ConfigBlock[] {
    return blocks.map((block) => {
        if (block.type === "array") {
            const items = block.items.map((item) => ({
                ...item,
                error: validateJson(item.value),
            }));
            const hasErrors = items.some((i) => i.error !== null);
            return { ...block, items, error: hasErrors ? "Has invalid items" : null };
        }

        const error = validateJson(block.rawValue);
        return { ...block, error };
    });
}

export function useBlockConfig(initialConfig: string) {
    const [blocks, setBlocks] = useState<ConfigBlock[]>(() =>
        validateBlocks(configToBlocks(initialConfig))
    );
    const lastSyncedConfig = useRef(initialConfig);

    const syncFromConfig = useCallback((configStr: string) => {
        if (configStr === lastSyncedConfig.current) return;
        lastSyncedConfig.current = configStr;
        setBlocks(validateBlocks(configToBlocks(configStr)));
    }, []);

    const toConfigString = useCallback(() => blocksToConfig(blocks), [blocks]);

    const hasErrors = blocks.some(
        (b) => b.error !== null
    );

    const errorCount = blocks.reduce((acc, b) => {
        if (b.type === "array") {
            return acc + b.items.filter((i) => i.error !== null).length;
        }
        return acc + (b.error ? 1 : 0);
    }, 0);

    const updateBlock = useCallback((blockId: string | number, updater: (b: ConfigBlock) => ConfigBlock) => {
        setBlocks((prev) => {
            const next = prev.map((b) => (b.id === blockId ? updater(b) : b));
            return validateBlocks(next);
        });
    }, []);

    const updateBlockRaw = useCallback((blockId: string | number, rawValue: string) => {
        updateBlock(blockId, (b) => ({ ...b, rawValue }));
    }, [updateBlock]);

    const updateItem = useCallback(
        (blockId: string | number, itemId: string | number, value: string) => {
            updateBlock(blockId, (b) => ({
                ...b,
                items: b.items.map((i) => (i.id === itemId ? { ...i, value } : i)),
            }));
        },
        [updateBlock]
    );

    const addBlock = useCallback((key: string, type: "object" | "array") => {
        const newBlock: ConfigBlock = {
            id: nextId(),
            key,
            type,
            collapsed: false,
            error: null,
            rawValue: type === "array" ? "[]" : "{}",
            items: [],
        };
        setBlocks((prev) => validateBlocks([...prev, newBlock]));
    }, []);

    const removeBlock = useCallback((blockId: string | number) => {
        setBlocks((prev) => prev.filter((b) => b.id !== blockId));
    }, []);

    const duplicateBlock = useCallback((blockId: string | number) => {
        setBlocks((prev) => {
            const idx = prev.findIndex((b) => b.id === blockId);
            if (idx === -1) return prev;
            const source = prev[idx];
            const clone: ConfigBlock = {
                ...source,
                id: nextId(),
                key: `${source.key}_copy`,
                items: source.items.map((i) => ({ ...i, id: nextItemId() })),
            };
            const next = [...prev];
            next.splice(idx + 1, 0, clone);
            return validateBlocks(next);
        });
    }, []);

    const addItem = useCallback((blockId: string | number) => {
        updateBlock(blockId, (b) => ({
            ...b,
            items: [...b.items, { id: nextItemId(), value: "{}", error: null }],
        }));
    }, [updateBlock]);

    const removeItem = useCallback((blockId: string | number, itemId: string | number) => {
        updateBlock(blockId, (b) => ({
            ...b,
            items: b.items.filter((i) => i.id !== itemId),
        }));
    }, [updateBlock]);

    const duplicateItem = useCallback(
        (blockId: string | number, itemId: string | number) => {
            updateBlock(blockId, (b) => {
                const idx = b.items.findIndex((i) => i.id === itemId);
                if (idx === -1) return b;
                const clone = { ...b.items[idx], id: nextItemId() };
                const items = [...b.items];
                items.splice(idx + 1, 0, clone);
                return { ...b, items };
            });
        },
        [updateBlock]
    );

    const reorderItems = useCallback(
        (blockId: string | number, newItems: ConfigBlockItem[]) => {
            updateBlock(blockId, (b) => ({ ...b, items: newItems }));
        },
        [updateBlock]
    );

    const toggleCollapse = useCallback((blockId: string | number) => {
        setBlocks((prev) =>
            prev.map((b) => (b.id === blockId ? { ...b, collapsed: !b.collapsed } : b))
        );
    }, []);

    const collapseAll = useCallback(() => {
        setBlocks((prev) => prev.map((b) => ({ ...b, collapsed: true })));
    }, []);

    const expandAll = useCallback(() => {
        setBlocks((prev) => prev.map((b) => ({ ...b, collapsed: false })));
    }, []);

    const renameBlock = useCallback((blockId: string | number, key: string) => {
        setBlocks((prev) =>
            prev.map((b) => (b.id === blockId ? { ...b, key } : b))
        );
    }, []);

    return {
        blocks,
        hasErrors,
        errorCount,
        syncFromConfig,
        toConfigString,
        updateBlockRaw,
        updateItem,
        addBlock,
        removeBlock,
        duplicateBlock,
        addItem,
        removeItem,
        duplicateItem,
        reorderItems,
        toggleCollapse,
        collapseAll,
        expandAll,
        renameBlock,
    };
}

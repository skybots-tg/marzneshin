import type { UniqueIdentifier } from "@dnd-kit/core";

export interface ConfigBlockItem {
    id: UniqueIdentifier;
    value: string;
    error: string | null;
}

export interface ConfigBlock {
    id: UniqueIdentifier;
    key: string;
    type: "object" | "array";
    collapsed: boolean;
    error: string | null;
    rawValue: string;
    items: ConfigBlockItem[];
}

export type EditorMode = "blocks" | "raw";

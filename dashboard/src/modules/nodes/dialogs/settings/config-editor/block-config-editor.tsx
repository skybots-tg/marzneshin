import type { FC } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { ConfigBlock, ConfigBlockItem } from "./types";
import { SectionBlock } from "./section-block";
import { BlockToolbar } from "./block-toolbar";

interface BlockConfigEditorProps {
    blocks: ConfigBlock[];
    onToggleCollapse: (blockId: string | number) => void;
    onDuplicate: (blockId: string | number) => void;
    onRemove: (blockId: string | number) => void;
    onUpdateRaw: (blockId: string | number, value: string) => void;
    onUpdateItem: (blockId: string | number, itemId: string | number, value: string) => void;
    onDuplicateItem: (blockId: string | number, itemId: string | number) => void;
    onRemoveItem: (blockId: string | number, itemId: string | number) => void;
    onReorderItems: (blockId: string | number, newItems: ConfigBlockItem[]) => void;
    onAddItem: (blockId: string | number) => void;
    onAddSection: (key: string, type: "object" | "array") => void;
    onCollapseAll: () => void;
    onExpandAll: () => void;
}

const blockVariants = {
    initial: { opacity: 0, y: -8, scale: 0.98 },
    animate: { opacity: 1, y: 0, scale: 1 },
    exit: { opacity: 0, y: 8, scale: 0.98 },
};

export const BlockConfigEditor: FC<BlockConfigEditorProps> = ({
    blocks,
    onToggleCollapse,
    onDuplicate,
    onRemove,
    onUpdateRaw,
    onUpdateItem,
    onDuplicateItem,
    onRemoveItem,
    onReorderItems,
    onAddItem,
    onAddSection,
    onCollapseAll,
    onExpandAll,
}) => {
    return (
        <div className="space-y-3">
            <BlockToolbar
                onCollapseAll={onCollapseAll}
                onExpandAll={onExpandAll}
                onAddSection={onAddSection}
            />
            <div className="space-y-2">
                <AnimatePresence initial={false} mode="popLayout">
                    {blocks.map((block) => (
                        <motion.div
                            key={block.id}
                            variants={blockVariants}
                            initial="initial"
                            animate="animate"
                            exit="exit"
                            transition={{ duration: 0.2, ease: "easeOut" }}
                            layout
                        >
                            <SectionBlock
                                block={block}
                                onToggleCollapse={() => onToggleCollapse(block.id)}
                                onDuplicate={() => onDuplicate(block.id)}
                                onRemove={() => onRemove(block.id)}
                                onUpdateRaw={(val) => onUpdateRaw(block.id, val)}
                                onUpdateItem={(itemId, val) =>
                                    onUpdateItem(block.id, itemId, val)
                                }
                                onDuplicateItem={(itemId) =>
                                    onDuplicateItem(block.id, itemId)
                                }
                                onRemoveItem={(itemId) =>
                                    onRemoveItem(block.id, itemId)
                                }
                                onReorderItems={(items) =>
                                    onReorderItems(block.id, items)
                                }
                                onAddItem={() => onAddItem(block.id)}
                            />
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>
        </div>
    );
};

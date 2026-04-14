import type { FC } from "react";
import {
    Sortable,
} from "@marzneshin/common/components/ui/sortable";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import type { ConfigBlock, ConfigBlockItem } from "./types";
import { ArrayItemBlock } from "./array-item-block";
import { AddButton } from "./block-actions";

interface ArrayBlockProps {
    block: ConfigBlock;
    onUpdateItem: (itemId: string | number, value: string) => void;
    onDuplicateItem: (itemId: string | number) => void;
    onRemoveItem: (itemId: string | number) => void;
    onReorder: (newItems: ConfigBlockItem[]) => void;
    onAddItem: () => void;
}

const itemVariants = {
    initial: { opacity: 0, height: 0 },
    animate: { opacity: 1, height: "auto" },
    exit: { opacity: 0, height: 0 },
};

export const ArrayBlock: FC<ArrayBlockProps> = ({
    block,
    onUpdateItem,
    onDuplicateItem,
    onRemoveItem,
    onReorder,
    onAddItem,
}) => {
    const { t } = useTranslation();

    return (
        <div className="space-y-2">
            <Sortable
                value={block.items}
                onValueChange={onReorder}
            >
                <div className="space-y-2">
                    <AnimatePresence initial={false}>
                        {block.items.map((item, idx) => (
                            <motion.div
                                key={item.id}
                                variants={itemVariants}
                                initial="initial"
                                animate="animate"
                                exit="exit"
                                transition={{ duration: 0.15, ease: "easeOut" }}
                            >
                                <ArrayItemBlock
                                    item={item}
                                    index={idx}
                                    onUpdate={(val) => onUpdateItem(item.id, val)}
                                    onDuplicate={() => onDuplicateItem(item.id)}
                                    onRemove={() => onRemoveItem(item.id)}
                                />
                            </motion.div>
                        ))}
                    </AnimatePresence>
                </div>
            </Sortable>
            <AddButton
                onClick={onAddItem}
                label={t("add")}
            />
        </div>
    );
};

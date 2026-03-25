import type { FC, HTMLAttributes } from "react";
import { Search } from 'lucide-react';

export const SearchBox: FC<HTMLAttributes<HTMLDivElement>> = ({ ...props }) => {
    return (
        <div
            className="bg-secondary/60 hover:bg-secondary border border-border/50 hover:border-border p-2 md:w-56 flex flex-row items-center rounded-lg justify-between transition-colors duration-200 cursor-pointer"
            {...props}
        >
            <div className="flex flex-row items-center gap-2">
                <Search className="size-4 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Search</p>
            </div>
            <kbd className="pointer-events-none hidden md:inline-flex h-5 select-none items-center gap-1 rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
                <span className="text-xs">&#8984;</span>K
            </kbd>
        </div>
    );
};

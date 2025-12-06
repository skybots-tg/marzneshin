import type { FC, HTMLAttributes } from "react";
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faMagnifyingGlass } from '@fortawesome/free-solid-svg-icons';

export const SearchBox: FC<HTMLAttributes<HTMLDivElement>> = ({ ...props }) => {
    return (
        <div
            className="bg-background/30 backdrop-blur-md border-2 border-primary/30 p-2 md:w-60 flex flex-row items-center rounded-md justify-between hover:border-primary/50 hover:shadow-[0_0_15px_rgba(0,255,255,0.2)] transition-all duration-300"
            {...props}
        >
            <div className="flex flex-row items-center gap-2">
                <FontAwesomeIcon icon={faMagnifyingGlass} className="size-4 text-primary" />
                <p className="text-sm text-primary font-header uppercase tracking-wider">Search</p>
            </div>
            <kbd className="pointer-events-none md:inline-flex h-5 select-none items-center gap-1 rounded bg-primary/20 border border-primary/50 px-1.5 font-mono text-[10px] font-medium text-primary hidden">
                <span className="text-xs">CTRL</span>K
            </kbd>
        </div>
    );
};

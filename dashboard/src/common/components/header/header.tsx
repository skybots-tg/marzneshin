import type { FC } from "react";

interface HeaderProps {
    start?: React.ReactNode;
    center?: React.ReactNode;
    end?: React.ReactNode;
}

export const Header: FC<HeaderProps> = ({ start, center, end }) => (
    <header className="h-14 shrink-0 relative z-20">
        <div className="glass flex flex-row items-center justify-between gap-2 px-3 md:px-4 w-full h-full text-foreground transition-smooth">
            <div className="flex flex-row gap-2 items-center shrink-0">
                {start}
            </div>
            <div className="flex-1 flex justify-center min-w-0 mx-2">
                {center}
            </div>
            <div className="flex flex-row gap-1.5 items-center shrink-0">
                {end}
            </div>
        </div>
    </header>
);

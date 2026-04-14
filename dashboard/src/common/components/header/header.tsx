import type { FC } from "react";

interface HeaderProps {
    start?: React.ReactNode;
    center?: React.ReactNode;
    end?: React.ReactNode;
}

export const Header: FC<HeaderProps> = ({ start, center, end }) => (
    <header className="h-[52px] shrink-0 relative z-20">
        <div className="flex flex-row items-center justify-between gap-3 px-4 md:px-5 w-full h-full text-foreground bg-card/80 backdrop-blur-2xl saturate-[1.8] border-b border-border/30 transition-all duration-250 ease-[cubic-bezier(0.25,0.1,0.25,1)]">
            <div className="flex flex-row gap-2.5 items-center shrink-0">
                {start}
            </div>
            <div className="flex-1 flex justify-center min-w-0 mx-3">
                {center}
            </div>
            <div className="flex flex-row gap-1.5 items-center shrink-0">
                {end}
            </div>
        </div>
    </header>
);

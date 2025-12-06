import type { FC } from "react";


interface HeaderProps {
    start?: React.ReactNode;
    center?: React.ReactNode;
    end?: React.ReactNode;
}

export const Header: FC<HeaderProps> = ({ start, center, end }) => (
    <header className="h-[3.5rem] relative">
        <div className="flex flex-row justify-between justify-items-stretch items-center lg:grid grid-cols-3 p-1 px-4 w-full h-full bg-gradient-to-r from-primary/90 via-primary to-primary/90 text-primary-foreground border-b-2 border-primary/50 shadow-[0_4px_20px_rgba(0,255,255,0.3)] backdrop-blur-sm relative z-10">
            <div className="absolute inset-0 bg-cyber-grid bg-grid opacity-10 pointer-events-none" />
            <div className="flex flex-row gap-2 justify-center-start justify-start items-center relative z-10">
                {start}
            </div>
            <div className="justify-center justify-self-center relative z-10">
                {center}
            </div>
            <div className="flex flex-row gap-2 h-10 justify-end justify-self-end items-center relative z-10">
                {end}
            </div>
        </div>
    </header>
);

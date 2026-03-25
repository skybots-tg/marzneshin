import { ShieldCheck } from 'lucide-react';

export const HeaderLogo = () => {
    return (
        <div className="flex flex-row gap-2 items-center px-2 py-1.5 h-9 rounded-lg hover:bg-secondary/60 transition-colors cursor-pointer">
            <ShieldCheck className="size-5 text-primary" />
            <span className="hidden md:inline text-sm font-semibold tracking-tight text-foreground">
                MARZNESHIN
            </span>
        </div>
    );
};

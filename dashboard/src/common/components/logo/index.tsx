import { ShieldCheck } from 'lucide-react';

export const HeaderLogo = () => {
    return (
        <div className="flex flex-row gap-2.5 items-center px-2 py-1.5 h-8 rounded-lg hover:bg-secondary/50 transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)] cursor-pointer active:scale-[0.97]">
            <ShieldCheck className="size-[18px] text-primary" />
            <span className="hidden md:inline text-[13px] font-semibold tracking-tight text-foreground">
                Marzneshin
            </span>
        </div>
    );
};

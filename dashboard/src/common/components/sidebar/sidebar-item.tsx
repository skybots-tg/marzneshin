import { Link } from "@tanstack/react-router";
import type { FC } from "react";
import type { SidebarItem as SidebarItemType } from "./types";
import { cn } from "@marzneshin/common/utils";
import { type VariantProps, cva } from "class-variance-authority";
import { useSidebarContext } from "./sidebar-provider";

const sidebarItemVariants = cva("w-full rounded-lg border-2 p-2 transition-all duration-300 relative overflow-hidden group", {
    variants: {
        variant: {
            default: "bg-background/40 backdrop-blur-sm text-foreground hover:bg-accent/15 border-primary/15 hover:border-primary/35 hover:shadow-[0_0_10px_rgba(0,200,200,0.12)] dark:hover:shadow-[0_0_15px_rgba(0,255,255,0.2)]",
            active: "bg-gradient-to-r from-primary/15 to-secondary/15 text-primary border-primary/40 shadow-[0_0_15px_rgba(0,200,200,0.2)] dark:shadow-[0_0_20px_rgba(0,255,255,0.3)] font-bold",
        },
        size: {
            default: "",
            collapsed: "",
        },
    },
});

export interface SidebarItemProps
    extends React.HTMLAttributes<HTMLLinkElement>,
    VariantProps<typeof sidebarItemVariants> {
    item: SidebarItemType;
}

export const SidebarItem: FC<SidebarItemProps> = ({
    item,
    className,
    variant,
}) => {
    const { collapsed, setOpen } = useSidebarContext();
    return (
        <li
            key={item.title}
            className={cn(sidebarItemVariants({ variant, className }))}
        >
            <Link
                to={item.to}
                onClick={() => setOpen?.(false)}
                className={cn("flex flex-row items-center justify-center font-header uppercase tracking-wider text-sm", {
                    "-justify-center gap-2": !collapsed,
                })}
            >
                <span className={cn("transition-transform duration-300", {
                    "group-hover:scale-110": true
                })}>{item.icon}</span>
                {!collapsed && <span className="transition-all duration-300">{item.title}</span>}
            </Link>
        </li>
    );
};

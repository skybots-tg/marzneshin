import { Link } from "@tanstack/react-router";
import type { FC } from "react";
import type { SidebarItem as SidebarItemType } from "./types";
import { cn } from "@marzneshin/common/utils";
import { type VariantProps, cva } from "class-variance-authority";
import { useSidebarContext } from "./sidebar-provider";

const sidebarItemVariants = cva("w-full rounded-lg p-2 transition-smooth relative group", {
    variants: {
        variant: {
            default: "glass-sm text-foreground hover:bg-accent/50 hover:scale-[1.02]",
            active: "glass text-primary font-semibold shadow-md",
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
                className={cn("flex flex-row items-center justify-center font-medium text-sm", {
                    "-justify-center gap-2": !collapsed,
                })}
            >
                <span className={cn("transition-smooth", {
                    "group-hover:scale-110": true
                })}>{item.icon}</span>
                {!collapsed && <span className="transition-smooth">{item.title}</span>}
            </Link>
        </li>
    );
};

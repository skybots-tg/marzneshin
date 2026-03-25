import { Link } from "@tanstack/react-router";
import type { FC } from "react";
import type { SidebarItem as SidebarItemType } from "./types";
import { cn } from "@marzneshin/common/utils";
import { type VariantProps, cva } from "class-variance-authority";
import { useSidebarContext } from "./sidebar-provider";

const sidebarItemVariants = cva(
    "w-full rounded-lg px-3 py-2 transition-all duration-200 relative group",
    {
        variants: {
            variant: {
                default: "text-muted-foreground hover:text-foreground hover:bg-secondary/80",
                active: "text-primary bg-primary/10 font-medium",
            },
            size: {
                default: "",
                collapsed: "",
            },
        },
    }
);

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
                className={cn(
                    "flex flex-row items-center text-sm gap-3",
                    collapsed && "justify-center"
                )}
            >
                <span className="shrink-0">{item.icon}</span>
                {!collapsed && <span className="truncate">{item.title}</span>}
            </Link>
        </li>
    );
};

import { SidebarItem } from "@marzneshin/common/components";
import { Link } from "@tanstack/react-router";
import { FC } from "react";
import { Box, Home, Server, ServerCog, UsersIcon } from 'lucide-react';
import { useIsCurrentRoute } from "@marzneshin/common/hooks";
import { cn } from "@marzneshin/common/utils";
import { useTranslation } from "react-i18next";

type BottomMenuItemProps = Omit<SidebarItem, 'isParent' | 'subItem'>

const BottomMenuItem: FC<BottomMenuItemProps & { active: boolean }> = ({ title, icon, to, active }) => {
    const { t } = useTranslation();
    return (
        <Link
            to={to}
            className={cn(
                "flex flex-col items-center justify-center gap-0.5 py-1.5 px-1 min-w-[3.5rem] rounded-2xl text-[10px] font-medium",
                "transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)]",
                active
                    ? "text-primary"
                    : "text-muted-foreground/70 hover:text-foreground active:scale-[0.92]"
            )}
        >
            <span className={cn(
                "p-1 rounded-xl transition-all duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]",
                active && "bg-primary/10 scale-105"
            )}>
                {icon}
            </span>
            <span className="truncate max-w-[4rem]">{t(title)}</span>
        </Link>
    )
}

const adminItems: BottomMenuItemProps[] = [
    {
        title: 'home',
        to: '/',
        icon: <Home className="size-[22px]" />,
    },
    {
        title: 'users',
        to: '/users',
        icon: <UsersIcon className="size-[22px]" />,
    },
]

const sudoAdminItems: BottomMenuItemProps[] = [
    {
        title: 'home',
        to: '/',
        icon: <Home className="size-[22px]" />,
    },
    {
        title: 'users',
        to: '/users',
        icon: <UsersIcon className="size-[22px]" />,
    },
    {
        title: 'services',
        to: '/services',
        icon: <Server className="size-[22px]" />,
    },
    {
        title: 'nodes',
        to: '/nodes',
        icon: <Box className="size-[22px]" />,
    },
    {
        title: 'hosts',
        to: '/hosts',
        icon: <ServerCog className="size-[22px]" />,
    },
]

export const DashboardBottomMenu = ({ variant = "admin" }: { variant: "sudo-admin" | "admin" }) => {
    const { isCurrentRouteActive } = useIsCurrentRoute()
    const items = variant === "sudo-admin" ? sudoAdminItems : adminItems;
    return (
        <nav className="flex flex-row items-center justify-around w-full px-2 py-1.5">
            {items.map((item: BottomMenuItemProps) => (
                <BottomMenuItem
                    key={item.to}
                    active={isCurrentRouteActive(item.to)}
                    {...item}
                />
            ))}
        </nav>
    )
}

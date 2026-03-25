import { SidebarItem } from "@marzneshin/common/components";
import i18n from "@marzneshin/features/i18n";
import { Link } from "@tanstack/react-router";
import { FC } from "react";
import { Box, Home, Server, ServerCog, UsersIcon } from 'lucide-react';
import { useIsCurrentRoute } from "@marzneshin/common/hooks";
import { cn } from "@marzneshin/common/utils";

type BottomMenuItemProps = Omit<SidebarItem, 'isParent' | 'subItem'>

const BottomMenuItem: FC<BottomMenuItemProps & { active: boolean }> = ({ title, icon, to, active }) => {
    return (
        <Link
            to={to}
            className={cn(
                "flex flex-col items-center justify-center gap-0.5 py-2 px-1 min-w-[3rem] rounded-xl text-[11px] font-medium transition-all duration-200",
                active
                    ? "text-primary bg-primary/10"
                    : "text-muted-foreground hover:text-foreground"
            )}
        >
            <span className={cn(
                "transition-transform duration-200",
                active && "scale-110"
            )}>
                {icon}
            </span>
            <span className="truncate max-w-[4rem]">{title}</span>
        </Link>
    )
}

const adminItems: BottomMenuItemProps[] = [
    {
        title: i18n.t('home'),
        to: '/',
        icon: <Home className="size-5" />,
    },
    {
        title: i18n.t('users'),
        to: '/users',
        icon: <UsersIcon className="size-5" />,
    },
]

const sudoAdminItems: BottomMenuItemProps[] = [
    {
        title: i18n.t('home'),
        to: '/',
        icon: <Home className="size-5" />,
    },
    {
        title: i18n.t('users'),
        to: '/users',
        icon: <UsersIcon className="size-5" />,
    },
    {
        title: i18n.t('services'),
        to: '/services',
        icon: <Server className="size-5" />,
    },
    {
        title: i18n.t('nodes'),
        to: '/nodes',
        icon: <Box className="size-5" />,
    },
    {
        title: i18n.t('hosts'),
        to: '/hosts',
        icon: <ServerCog className="size-5" />,
    },
]

export const DashboardBottomMenu = ({ variant = "admin" }: { variant: "sudo-admin" | "admin" }) => {
    const { isCurrentRouteActive } = useIsCurrentRoute()
    const items = variant === "sudo-admin" ? sudoAdminItems : adminItems;
    return (
        <nav className="flex flex-row items-center justify-around w-full px-2 py-1">
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

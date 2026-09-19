import {
    SidebarItem,
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
} from "@marzneshin/common/components";
import { Link } from "@tanstack/react-router";
import { FC, useState } from "react";
import {
    Box,
    Home,
    Network,
    Server,
    UsersIcon,
    ShieldCheck,
    Settings,
    Waypoints,
    Activity,
    Bot,
    MoreHorizontal,
} from "lucide-react";
import { useIsCurrentRoute } from "@marzneshin/common/hooks";
import { cn } from "@marzneshin/common/utils";
import { useTranslation } from "react-i18next";

type BottomMenuItemProps = Omit<SidebarItem, "isParent" | "subItem">;

const itemClass = (active: boolean) =>
    cn(
        "flex flex-col items-center justify-center gap-0.5 py-1.5 px-1 flex-1 min-w-0 rounded-2xl text-[10px] font-medium",
        "transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)]",
        active
            ? "text-primary"
            : "text-muted-foreground/70 hover:text-foreground active:scale-[0.92]",
    );

const iconWrapClass = (active: boolean) =>
    cn(
        "p-1 rounded-xl transition-all duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]",
        active && "bg-primary/10 scale-105",
    );

const BottomMenuItem: FC<BottomMenuItemProps & { active: boolean }> = ({
    title,
    icon,
    to,
    active,
}) => {
    const { t } = useTranslation();
    return (
        <Link to={to} className={itemClass(active)}>
            <span className={iconWrapClass(active)}>{icon}</span>
            <span className="truncate max-w-full">{t(title)}</span>
        </Link>
    );
};

const size = "size-[22px]";

/**
 * Что помещается в нижнюю панель.
 *
 * Раньше сюда складывали все семь разделов подряд. На экране в 375 точек это
 * по 53 точки на пункт — подписи обрезались до неузнаваемости, а попасть
 * пальцем можно было в соседний. При этом три раздела — топология, здоровье
 * бриджей и ассистент — в нижнее меню вообще не попали, то есть с телефона
 * были недоступны совсем.
 *
 * Теперь четыре частых раздела остаются на виду, остальные уходят в «Ещё».
 * Список там собирается из того же перечня, что и боковое меню, поэтому новый
 * раздел больше не может потеряться по дороге на телефон.
 */
const primaryItems: BottomMenuItemProps[] = [
    { title: "home", to: "/", icon: <Home className={size} /> },
    { title: "users", to: "/users", icon: <UsersIcon className={size} /> },
    { title: "nodes", to: "/nodes", icon: <Box className={size} /> },
    { title: "hosts", to: "/hosts", icon: <Network className={size} /> },
];

const moreItems: BottomMenuItemProps[] = [
    { title: "services", to: "/services", icon: <Server className={size} /> },
    { title: "topology", to: "/topology", icon: <Waypoints className={size} /> },
    {
        title: "bridge-health",
        to: "/bridge-health",
        icon: <Activity className={size} />,
    },
    { title: "admins", to: "/admins", icon: <ShieldCheck className={size} /> },
    { title: "ai-assistant", to: "/ai", icon: <Bot className={size} /> },
    { title: "settings", to: "/settings", icon: <Settings className={size} /> },
];

const adminItems: BottomMenuItemProps[] = [
    { title: "home", to: "/", icon: <Home className={size} /> },
    { title: "users", to: "/users", icon: <UsersIcon className={size} /> },
];

const MoreSheet: FC = () => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const { isCurrentRouteActive } = useIsCurrentRoute();
    const active = moreItems.some((i) => isCurrentRouteActive(i.to));

    return (
        <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger className={itemClass(active)}>
                <span className={iconWrapClass(active)}>
                    <MoreHorizontal className={size} />
                </span>
                <span className="truncate max-w-full">{t("more")}</span>
            </SheetTrigger>
            <SheetContent side="bottom" className="rounded-t-2xl">
                <SheetHeader className="mb-4">
                    <SheetTitle className="text-left text-base">
                        {t("more")}
                    </SheetTitle>
                </SheetHeader>
                <nav className="grid grid-cols-3 gap-2 pb-4">
                    {moreItems.map((item) => (
                        <Link
                            key={item.to}
                            to={item.to}
                            onClick={() => setOpen(false)}
                            className={cn(
                                "flex flex-col items-center justify-center gap-2 py-4 rounded-xl border border-border/60",
                                "text-xs font-medium text-center",
                                isCurrentRouteActive(item.to)
                                    ? "text-primary border-primary/40 bg-primary/[0.06]"
                                    : "text-muted-foreground active:scale-[0.97]",
                            )}
                        >
                            {item.icon}
                            <span className="px-1 leading-tight">
                                {t(item.title)}
                            </span>
                        </Link>
                    ))}
                </nav>
            </SheetContent>
        </Sheet>
    );
};

export const DashboardBottomMenu = ({
    variant = "admin",
}: {
    variant: "sudo-admin" | "admin";
}) => {
    const { isCurrentRouteActive } = useIsCurrentRoute();

    if (variant !== "sudo-admin") {
        return (
            <nav className="flex flex-row items-center justify-around w-full px-2 py-1.5">
                {adminItems.map((item) => (
                    <BottomMenuItem
                        key={item.to}
                        active={isCurrentRouteActive(item.to)}
                        {...item}
                    />
                ))}
            </nav>
        );
    }

    return (
        <nav className="flex flex-row items-stretch w-full px-2 py-1.5">
            {primaryItems.map((item) => (
                <BottomMenuItem
                    key={item.to}
                    active={isCurrentRouteActive(item.to)}
                    {...item}
                />
            ))}
            <MoreSheet />
        </nav>
    );
};

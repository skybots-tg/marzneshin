import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    DropdownMenuGroup,
    Button,
} from "@marzneshin/common/components";
import { Link } from "@tanstack/react-router";
import { FC } from 'react';
import { Settings, MenuIcon, ShieldCheck } from "lucide-react";
import { LanguageSwitchMenu } from "@marzneshin/features/language-switch";
import { ThemeToggle } from "@marzneshin/features/theme-switch";
import { useAuth, Logout } from "@marzneshin/modules/auth";
import { useScreenBreakpoint } from "@marzneshin/common/hooks/use-screen-breakpoint";
import { useTranslation } from "react-i18next";
import { VersionIndicator } from "@marzneshin/features/version-indicator";

export const HeaderMenu: FC = () => {
    const isDesktop = useScreenBreakpoint("md");
    const { isSudo } = useAuth();
    const { t } = useTranslation();

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-full hover:bg-secondary/80"
                >
                    <MenuIcon className="size-[17px] text-foreground" />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70 px-3">
                    Menu
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {(!isDesktop && isSudo()) && (
                    <>
                        <DropdownMenuItem asChild>
                            <Link to="/settings" className="flex items-center justify-between w-full cursor-pointer">
                                {t("settings")}
                                <Settings className="size-4 text-muted-foreground" />
                            </Link>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <Link to="/admins" className="flex items-center justify-between w-full cursor-pointer">
                                {t("admins")}
                                <ShieldCheck className="size-4 text-muted-foreground" />
                            </Link>
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                    </>
                )}
                <DropdownMenuItem className="w-full">
                    <Logout />
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <LanguageSwitchMenu />
                    <ThemeToggle />
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup className="py-1 shrink-0">
                    <VersionIndicator />
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
};

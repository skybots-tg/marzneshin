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
                    className="bg-gradient-to-br from-primary/10 to-secondary/10 backdrop-blur-xl border border-border/50 hover:bg-accent/50 hover:border-primary/30 shadow-sm hover:shadow-md transition-all duration-300"
                    size="icon"
                >
                    <MenuIcon className="text-foreground" />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuLabel>Menu</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {(!isDesktop && isSudo()) && (
                    <>
                        <DropdownMenuItem className="w-full">
                            <Link to="/settings" className="hstack gap-1 items-center justify-between w-full h-fit p-0">
                                {t("settings")}
                                <Settings className="size-4 text-foreground" />
                            </Link>
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="w-full">
                            <Link to="/admins" className="hstack gap-1 items-center justify-between w-full h-fit p-0" >
                                {t("admins")}
                                <ShieldCheck className="size-4 text-foreground" />
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
        </DropdownMenu >
    )
};

import {
    Sidebar,
    type SidebarItem,
} from "@marzneshin/common/components";
import { useIsCurrentRoute } from "@marzneshin/common/hooks";
import type { FC } from "react";
import { sidebarItems as sidebarItemsSudoAdmin, sidebarItemsNonSudoAdmin } from ".";
import { cn } from "@marzneshin/common/utils";
import { useAuth } from "@marzneshin/modules/auth";
import { SupportUs } from "@marzneshin/features/support-us";
import { projectInfo } from "@marzneshin/common/utils";
import { useTranslation } from "react-i18next";

interface DashboardSidebarProps {
    collapsed: boolean;
    setCollapsed: (state: boolean) => void;
    open?: boolean;
    setOpen?: (state: boolean) => void;
}

export const DashboardSidebar: FC<DashboardSidebarProps> = ({
    collapsed,
    setCollapsed,
    setOpen,
    open,
}) => {
    const { isSudo } = useAuth();
    const { isCurrentRouteActive } = useIsCurrentRoute()
    const { t } = useTranslation();
    const sidebarItems = isSudo() ? sidebarItemsSudoAdmin : sidebarItemsNonSudoAdmin
    return (
        <aside className="size-full py-3 px-3">
            <nav className="size-full">
                <Sidebar
                    sidebar={sidebarItems}
                    collapsed={collapsed}
                    setCollapsed={setCollapsed}
                    open={open}
                    setOpen={setOpen}
                >
                    <div className="flex size-full flex-col justify-between">
                        <Sidebar.Body>
                            {Object.keys(sidebarItems).map((key) => (
                                <div className="w-full" key={key}>
                                    <Sidebar.Group className="uppercase text-[10px] tracking-[0.1em] font-semibold text-muted-foreground/50 mb-1.5 px-3">
                                        {t(key)}
                                    </Sidebar.Group>
                                    {sidebarItems[key].map((item: SidebarItem) => (
                                        <Sidebar.Item
                                            variant={isCurrentRouteActive(item.to) ? "active" : "default"}
                                            className={cn("my-0.5", {
                                                "w-10 h-10": collapsed,
                                            })}
                                            item={item}
                                            key={item.title}
                                        />
                                    ))}
                                </div>
                            ))}
                        </Sidebar.Body>
                        <Sidebar.Footer>
                            {collapsed ?
                                <SupportUs variant="view" donationLink={projectInfo.donationLink} structure="popover" />
                                :
                                <SupportUs variant="local-storage" donationLink={projectInfo.donationLink} structure="card" />
                            }
                        </Sidebar.Footer>
                    </div>
                </Sidebar>
            </nav>
        </aside>
    );
};

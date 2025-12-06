import {
    Header,
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
    Toaster,
    Loading,
    HeaderLogo,
    HeaderMenu,
} from "@marzneshin/common/components";
import { useAuth } from "@marzneshin/modules/auth";
import { DashboardSidebar, ToggleButton } from "@marzneshin/features/sidebar";
import { usePanelToggle } from "@marzneshin/features/sidebar/use-panel-toggle";
import { useScreenBreakpoint } from "@marzneshin/common/hooks/use-screen-breakpoint";
import { cn } from "@marzneshin/common/utils";
import { Suspense } from "react";
import {
    Outlet,
    Link,
    createFileRoute,
    redirect
} from "@tanstack/react-router";
import { useGithubRepoStatsQuery, GithubRepo } from "@marzneshin/features/github-repo";
import { CommandBox } from "@marzneshin/features/search-command";
import { DashboardBottomMenu } from "@marzneshin/features/bottom-menu";

export const DashboardLayout = () => {
    const isDesktop = useScreenBreakpoint("md");
    const {
        collapsed,
        panelRef,
        setCollapsed,
        toggleCollapse,
    } = usePanelToggle(isDesktop);
    const { isSudo } = useAuth();
    const { data: stats } = useGithubRepoStatsQuery()

    return (
        <div className="flex flex-col w-screen h-screen relative">
            <Header
                start={
                    <>
                        <Link to="/">
                            <HeaderLogo />
                        </Link>
                        {isDesktop && (

                            <ToggleButton
                                collapsed={collapsed}
                                onToggle={toggleCollapse}
                            />
                        )}
                    </>
                }
                center={<CommandBox />}
                end={
                    <>
                        <GithubRepo {...stats} variant={isDesktop ? "full" : "mini"} />
                        <HeaderMenu />
                    </>
                }
            />
            <div className="flex flex-1 overflow-hidden relative z-10">
                {isDesktop ? (
                    <ResizablePanelGroup direction="horizontal" className="flex h-full w-full">
                        <ResizablePanel
                            collapsible
                            collapsedSize={2}
                            onCollapse={() => setCollapsed(true)}
                            onExpand={() => setCollapsed(false)}
                            minSize={15}
                            className={cn("w-[120px] min-w-[70px] border-r-2 border-primary/20 bg-background/90 backdrop-blur-lg")}
                            defaultSize={20}
                            ref={panelRef}
                            maxSize={30}
                        >
                            <DashboardSidebar
                                collapsed={collapsed}
                                setCollapsed={setCollapsed}
                            />
                        </ResizablePanel>
                        <ResizableHandle withHandle className="w-[2px] bg-gradient-to-b from-primary/40 via-secondary/40 to-primary/40 hover:shadow-[0_0_8px_rgba(0,200,200,0.4)] dark:hover:shadow-[0_0_10px_rgba(0,255,255,0.5)] transition-all duration-300" />
                        <ResizablePanel className="flex flex-col h-full bg-background/60 backdrop-blur-sm">
                            <main className="flex-grow flex flex-col overflow-y-auto p-4">
                                <Suspense fallback={<Loading />}>
                                    <Outlet />
                                </Suspense>
                            </main>
                        </ResizablePanel>
                    </ResizablePanelGroup>
                ) : (
                    <div className="flex flex-col h-full w-full bg-background/50 backdrop-blur-sm">
                        <main className="flex flex-col h-full overflow-y-auto">
                            <Suspense fallback={<Loading />}>
                                <Outlet />
                            </Suspense>
                            <footer className="h-30 border-t-3 border-primary/30 shrink-0 py-2 px-5 bg-background/80 backdrop-blur-md">
                                <DashboardBottomMenu variant={isSudo() ? "sudo-admin" : "admin"} />
                            </footer>
                        </main>
                    </div>
                )}
            </div>
            <Toaster position="top-center" />
        </div>
    );
};

export const Route = createFileRoute("/_dashboard")({
    component: () => <DashboardLayout />,
    beforeLoad: async () => {
        const loggedIn = await useAuth.getState().isLoggedIn();
        if (!loggedIn) {
            throw redirect({
                to: "/login",
            });
        }
    },
});

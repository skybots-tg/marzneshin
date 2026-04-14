import {
    createFileRoute,
    defer,
    Await,
    Outlet,
    useNavigate,
} from "@tanstack/react-router";
import {
    fetchNode,
    RouterNodeContext
} from "@marzneshin/modules/nodes";
import { Suspense } from "react";
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogTitle,
    AlertDialogFooter,
    Loading,
    Button,
} from "@marzneshin/common/components";
import { useTranslation } from "react-i18next";

const NodeProvider = () => {
    const { node } = Route.useLoaderData()

    return (
        <Suspense fallback={<Loading inline />}>
            <Await promise={node}>
                {(node) => (
                    <RouterNodeContext.Provider value={{ node }}>
                        <Suspense>
                            <Outlet />
                        </Suspense>
                    </RouterNodeContext.Provider>
                )}
            </Await>
        </Suspense>
    );
};

const NodeNotFound = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    return (
        <AlertDialog open={true}>
            <AlertDialogContent>
                <AlertDialogTitle>{t('not-found', { entity: t('nodes') })}</AlertDialogTitle>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => navigate({ to: '/nodes' })}>
                        {t('go-back')}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

export const Route = createFileRoute('/_dashboard/nodes/$nodeId')({
    loader: async ({ params }) => {
        const nodePromise = fetchNode({
            queryKey: ["nodes", Number.parseInt(params.nodeId)]
        });

        return {
            node: defer(nodePromise)
        }
    },
    component: NodeProvider,
    errorComponent: NodeNotFound,
})

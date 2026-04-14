import {
    createFileRoute,
    defer,
    Await,
    Outlet,
    useNavigate,
} from "@tanstack/react-router";
import {
    RouterHostContext,
    fetchHost,
} from "@marzneshin/modules/hosts";
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

const HostProvider = () => {
    const { host } = Route.useLoaderData()
    return (
        <Suspense fallback={<Loading inline />}>
            <Await promise={host}>
                {(host) => (
                    <RouterHostContext.Provider value={{ host }}>
                        <Suspense>
                            <Outlet />
                        </Suspense>
                    </RouterHostContext.Provider>
                )}
            </Await>
        </Suspense>
    )
}

const HostNotFound = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    return (
        <AlertDialog open={true}>
            <AlertDialogContent>
                <AlertDialogTitle>{t('not-found', { entity: t('hosts') })}</AlertDialogTitle>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => navigate({ to: '/hosts' })}>
                        {t('go-back')}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

export const Route = createFileRoute('/_dashboard/hosts/$hostId')({
    loader: async ({ params }) => {
        const hostPromise = fetchHost({
            queryKey: ["hosts", Number.parseInt(params.hostId)]
        });

        return {
            host: defer(hostPromise)
        }
    },
    errorComponent: HostNotFound,
    component: HostProvider,
})

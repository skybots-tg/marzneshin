import {
    createFileRoute,
    defer,
    Await,
    Outlet,
    useNavigate,
} from "@tanstack/react-router";
import {
    RouterServiceContext,
    fetchService,
} from "@marzneshin/modules/services";
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

const ServiceProvider = () => {
    const { service } = Route.useLoaderData()
    return (
        <Suspense fallback={<Loading inline />}>
            <Await promise={service}>
                {(service) => (
                    <RouterServiceContext.Provider value={{ service }}>
                        <Suspense>
                            <Outlet />
                        </Suspense>
                    </RouterServiceContext.Provider>
                )}
            </Await>
        </Suspense>
    )
}

const ServiceNotFound = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    return (
        <AlertDialog open={true}>
            <AlertDialogContent>
                <AlertDialogTitle>{t('not-found', { entity: t('services') })}</AlertDialogTitle>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => navigate({ to: '/services' })}>
                        {t('go-back')}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

export const Route = createFileRoute('/_dashboard/services/$serviceId')({
    loader: async ({ params }) => {
        const servicePromise = fetchService({
            queryKey: ["services", Number.parseInt(params.serviceId)]
        });

        return {
            service: defer(servicePromise)
        }
    },
    errorComponent: ServiceNotFound,
    component: ServiceProvider,
})

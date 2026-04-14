import {
    createFileRoute,
    Outlet,
    useNavigate,
} from "@tanstack/react-router";
import { useSuspenseQuery } from "@tanstack/react-query";
import { queryClient } from "@marzneshin/common/utils";
import {
    RouterAdminContext,
    adminQueryOptions,
} from "@marzneshin/modules/admins";
import { Suspense, useMemo } from "react";
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogTitle,
    AlertDialogFooter,
    Button,
} from "@marzneshin/common/components";
import { useTranslation } from "react-i18next";

const AdminProvider = () => {
    const { username } = Route.useLoaderData()
    const { data: admin, isPending } = useSuspenseQuery(adminQueryOptions({ username }))
    const value = useMemo(() => ({ admin, isPending }), [admin, isPending])
    return (
        <RouterAdminContext.Provider value={value}>
            <Suspense>
                <Outlet />
            </Suspense>
        </RouterAdminContext.Provider>
    )
}

const AdminNotFound = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    return (
        <AlertDialog open={true}>
            <AlertDialogContent>
                <AlertDialogTitle>{t('not-found', { entity: t('admins') })}</AlertDialogTitle>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => navigate({ to: '/admins' })}>
                        {t('go-back')}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

export const Route = createFileRoute('/_dashboard/admins/$adminId')({
    loader: async ({ params }) => {
        queryClient.ensureQueryData(adminQueryOptions({ username: params.adminId }))
        return { username: params.adminId };
    },
    errorComponent: AdminNotFound,
    component: AdminProvider,
})

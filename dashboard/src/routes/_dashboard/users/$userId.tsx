import {
    createFileRoute,
    Outlet,
    useNavigate,
} from "@tanstack/react-router";
import { useSuspenseQuery } from "@tanstack/react-query";
import { queryClient } from "@marzneshin/common/utils";
import {
    RouterUserContext,
    userQueryOptions,
} from "@marzneshin/modules/users";
import { Suspense, useMemo } from "react";
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogTitle,
    AlertDialogFooter,
    Button,
} from "@marzneshin/common/components";
import { useTranslation } from "react-i18next";

const UserProvider = () => {
    const { username } = Route.useLoaderData()
    const { data: user, isPending } = useSuspenseQuery(userQueryOptions({ username }))
    const value = useMemo(() => ({ user, isPending }), [user, isPending])
    return (
        <RouterUserContext.Provider value={value}>
            <Suspense>
                <Outlet />
            </Suspense>
        </RouterUserContext.Provider>
    )
}

const UserNotFound = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    return (
        <AlertDialog open={true}>
            <AlertDialogContent>
                <AlertDialogTitle>{t('not-found', { entity: t('users') })}</AlertDialogTitle>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => navigate({ to: '/users' })}>
                        {t('go-back')}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

export const Route = createFileRoute('/_dashboard/users/$userId')({
    loader: async ({ params }) => {
        queryClient.ensureQueryData(userQueryOptions({ username: params.userId }))
        return { username: params.userId };
    },
    errorComponent: UserNotFound,
    component: UserProvider,
})

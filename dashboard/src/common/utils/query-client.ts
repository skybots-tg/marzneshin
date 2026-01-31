import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            // Don't refetch when window regains focus (user's request)
            refetchOnWindowFocus: false,
            // Always fetch fresh data when component mounts
            refetchOnMount: true,
        },
    },
});

import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            // Don't refetch when window regains focus
            refetchOnWindowFocus: false,
            // Don't refetch when reconnecting to network
            refetchOnReconnect: false,
            // Don't retry failed requests automatically
            retry: 1,
            // Keep data fresh for 5 minutes
            staleTime: 5 * 60 * 1000,
        },
    },
});

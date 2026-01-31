import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            // Don't refetch when window regains focus
            refetchOnWindowFocus: false,
            // Don't refetch when reconnecting to network  
            refetchOnReconnect: false,
        },
    },
});

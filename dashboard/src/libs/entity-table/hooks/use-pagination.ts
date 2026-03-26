import { useCallback, useState } from "react";
import { useLocalStorage } from "@uidotdev/usehooks";
import type { PaginationState, Updater } from "@tanstack/react-table";

export function usePagination({ entityKey, defaultPageSize = 10 }: { entityKey: string; defaultPageSize?: number }) {
    const [rowPerPageLocal] = useLocalStorage<number>(`marzneshin-table-row-per-page-${entityKey}`, defaultPageSize);
    const [pagination, setPagination] = useState({
        pageSize: rowPerPageLocal,
        pageIndex: 1,
    });
    const { pageSize, pageIndex } = pagination;

    const safePaginationChange = useCallback((updater: Updater<PaginationState>) => {
        setPagination((old) => {
            const next = typeof updater === "function" ? updater(old) : updater;
            return { ...next, pageIndex: Math.max(1, next.pageIndex) };
        });
    }, []);

    return {
        pageSize,
        pageIndex,
        onPaginationChange: safePaginationChange,
        pagination,
        skip: pageSize * pageIndex,
    };
}

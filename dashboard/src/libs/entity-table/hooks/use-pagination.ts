import { useState } from "react";
import { useLocalStorage } from "@uidotdev/usehooks";

export function usePagination({ entityKey, defaultPageSize = 10 }: { entityKey: string; defaultPageSize?: number }) {
    const [rowPerPageLocal] = useLocalStorage<number>(`marzneshin-table-row-per-page-${entityKey}`, defaultPageSize);
    const [pagination, setPagination] = useState({
        pageSize: rowPerPageLocal,
        pageIndex: 1,
    });
    const { pageSize, pageIndex } = pagination;

    return {
        pageSize,
        pageIndex,
        onPaginationChange: setPagination,
        pagination,
        skip: pageSize * pageIndex,
    };
}

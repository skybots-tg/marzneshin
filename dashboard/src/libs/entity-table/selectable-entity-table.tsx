import { useEffect, useMemo } from "react";
import { DataTableViewOptions } from "./components";
import { useQuery } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { EntityTableContext } from "./contexts";
import { TableSearch, DataTablePagination, EntityDataTable } from "./components";
import {
    type UseRowSelectionReturn,
    usePrimaryFiltering,
    usePagination,
    type FetchEntityReturn,
    useEntityTable,
    useVisibility,
    useSorting,
    type SelectableQueryKey,
    type SelectableEntityQueryKeyType,
    useFilters,
} from "./hooks";

export interface SelectableEntityTableProps<T extends { id: number }> {
    fetchEntity: ({ queryKey }: SelectableEntityQueryKeyType) => FetchEntityReturn<T>;
    columns: ColumnDef<T>[];
    primaryFilter: string;
    parentEntityKey: string;
    parentEntityId: string | number;
    entityKey: string;
    rowSelection: UseRowSelectionReturn;
    entitySelection: {
        selectedEntity: number[];
        setSelectedEntity: (s: number[]) => void;
    }
    existingEntityIds: number[];
}

export function SelectableEntityTable<T extends { id: number }>({
    fetchEntity,
    columns,
    primaryFilter,
    rowSelection,
    entitySelection,
    entityKey,
    parentEntityKey,
    parentEntityId,
}: SelectableEntityTableProps<T>) {
    const columnPrimaryFilter = usePrimaryFiltering({ column: primaryFilter });
    const filters = useFilters();
    const sorting = useSorting();
    const visibility = useVisibility();
    const { selectedRow } = rowSelection;
    const { setSelectedEntity } = entitySelection;
    const { onPaginationChange, pageIndex, pageSize } = usePagination({ entityKey });
    const query: SelectableQueryKey = [
        parentEntityKey,
        parentEntityId,
        entityKey,
        {
            page: pageIndex,
            size: pageSize,
        },
        columnPrimaryFilter.columnFilters,
        {
            sortBy: sorting.sorting[0]?.id || "created_at",
            desc: sorting.sorting[0]?.desc || true,
        },
        { filters: filters.columnsFilter }
    ];

    const { data, isFetching, isError, refetch } = useQuery({
        queryFn: fetchEntity,
        queryKey: query,
        initialData: { entities: [], pageCount: 1 },
    });

    const table = useEntityTable({
        data,
        columns,
        pageSize,
        pageIndex,
        rowSelection,
        visibility,
        sorting,
        onPaginationChange,
        getRowId: (row) => String(row.id),
    });

    useEffect(() => {
        const ids = Object.entries(selectedRow)
            .filter(([, value]) => value === true)
            .map(([key]) => Number(key))
            .filter((id) => Number.isFinite(id));

        setSelectedEntity(ids);
    }, [selectedRow, setSelectedEntity]);


    const contextValue = useMemo(
        () => ({ entityKey, table, data: data.entities, primaryFilter: columnPrimaryFilter, filters, isLoading: isFetching, isError, refetch }),
        [entityKey, table, data.entities, filters, columnPrimaryFilter, isFetching, isError, refetch],
    );

    return (
        <EntityTableContext.Provider value={contextValue}>
            <div className="flex flex-col">
                <div className="flex flex-col md:flex-row-reverse items-center py-4 gap-2 w-full">
                    <div className="flex flex-row items-center w-full">
                        <DataTableViewOptions table={table} />
                    </div>
                    <TableSearch />
                </div>
                <div className="w-full rounded-md border">
                    <EntityDataTable columns={columns} />
                    <DataTablePagination table={table} />
                </div>
            </div>
        </EntityTableContext.Provider>
    );
}

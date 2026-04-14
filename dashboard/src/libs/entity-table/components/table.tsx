import {
    ColumnDef,
    flexRender,
} from "@tanstack/react-table";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Skeleton,
    Button,
} from "@marzneshin/common/components";
import { useTranslation } from "react-i18next";
import { useEntityTableContext } from "@marzneshin/libs/entity-table/contexts";
import { type FC } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

interface DataTableProps<TData, TValue> {
    columns: ColumnDef<TData, TValue>[]
    onRowClick?: (object: TData) => void
    getRowClassName?: (original: TData) => string | undefined
}

const Headers = () => {
    const { table } = useEntityTableContext();
    return (
        table.getHeaderGroups().map(headerGroup => (
            <TableRow key={headerGroup.id}>
                {headerGroup.headers.map(header => (
                    <TableHead key={header.id}>
                        {!header.isPlaceholder && flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                ))}
            </TableRow>
        ))
    )
};

const Rows: FC<Readonly<DataTableProps<any, any>>> = ({
    columns,
    onRowClick,
    getRowClassName,
}) => {
    const { table } = useEntityTableContext();
    const { t } = useTranslation();

    return (table.getRowModel().rows?.length ? (
        table.getRowModel().rows.map(row => (
            <TableRow
                key={row.id}
                data-state={row.getIsSelected() ? "selected" : undefined}
                data-testid="entity-table-row"
                onClick={() => onRowClick?.(row.original)}
                className={getRowClassName?.(row.original)}
            >
                {row.getVisibleCells().map(cell => (
                    <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                ))}
            </TableRow>
        ))
    ) : (
        <TableRow>
            <TableCell colSpan={columns.length} className="h-24 text-center">
                {t('table.no-result')}
            </TableCell>
        </TableRow>
    ))
};

const Loading: FC<{ columnCount: number }> = ({ columnCount }) => (
    <>
        {Array.from({ length: 5 }).map((_, rowIndex) => (
            <TableRow key={`skeleton-row-${rowIndex}`} className="w-full">
                {Array.from({ length: columnCount }).map((_, colIndex) => (
                    <TableCell key={`skeleton-cell-${rowIndex}-${colIndex}`} className="h-12">
                        <Skeleton className="w-full h-full" />
                    </TableCell>
                ))}
            </TableRow>
        ))}
    </>
);

const ErrorState: FC<{ columnCount: number }> = ({ columnCount }) => {
    const { t } = useTranslation();
    const { refetch } = useEntityTableContext();
    return (
        <TableRow>
            <TableCell colSpan={columnCount} className="h-32">
                <div className="flex flex-col items-center justify-center gap-3 text-muted-foreground">
                    <AlertCircle className="size-8 text-destructive" />
                    <p className="text-sm font-medium">{t('table.error')}</p>
                    <Button variant="outline" size="sm" onClick={() => refetch()}>
                        <RefreshCw className="size-4 mr-2" />
                        {t('retry')}
                    </Button>
                </div>
            </TableCell>
        </TableRow>
    );
};

export function EntityDataTable<TData, TValue>({
    columns,
    onRowClick,
    getRowClassName,
}: Readonly<DataTableProps<TData, TValue>>) {
    const { isLoading, isError } = useEntityTableContext();
    const columnCount = columns.length;

    return (
        <Table className="w-full">
            <TableHeader> <Headers /> </TableHeader>
            <TableBody>
                {isError
                    ? <ErrorState columnCount={columnCount} />
                    : isLoading
                        ? <Loading columnCount={columnCount} />
                        : <Rows onRowClick={onRowClick} columns={columns} getRowClassName={getRowClassName} />}
            </TableBody>
        </Table>
    );
}

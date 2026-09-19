import { flexRender, type Row } from "@tanstack/react-table";
import { Button, Skeleton } from "@marzneshin/common/components";
import { cn } from "@marzneshin/common/utils";
import { useTranslation } from "react-i18next";
import { type FC } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { useEntityTableContext } from "../contexts";
import { ColumnLabelModeContext } from "../contexts/column-label-mode";

/**
 * Строка таблицы на узком экране.
 *
 * До этого на телефоне жила обычная `<table>`. У таблицы узлов тринадцать
 * колонок: на экране помещались полторы, остальное уезжало в горизонтальную
 * прокрутку, которой на карточке страницы к тому же не было видно. Читать это
 * было нельзя, и никакая правка отступов тут не помогала — не тот способ
 * показывать данные.
 *
 * Карточка раскладывает ту же строку вертикально. Разделение колонок берётся
 * из самого описания таблицы, а не из отдельного списка, который пришлось бы
 * поддерживать руками:
 *
 * - `select` — флажок выбора, он остаётся слева от заголовка;
 * - колонки без доступа к полю (`accessorFn` нет) — это кнопки: «actions»,
 *   «resync», «migrate». Им место в подвале карточки;
 * - первая колонка с полем — заголовок карточки;
 * - остальные — пары «подпись: значение».
 */

const CELL_LABEL = "text-xs text-muted-foreground shrink-0";

const RowCard = <TData,>({
    row,
    onRowClick,
    className,
}: {
    row: Row<TData>;
    onRowClick?: (object: TData) => void;
    className?: string;
}) => {
    const cells = row.getVisibleCells();
    const selectCell = cells.find((c) => c.column.id === "select");
    const displayCells = cells.filter(
        (c) => c.column.id !== "select" && c.column.accessorFn === undefined,
    );
    const fieldCells = cells.filter((c) => c.column.accessorFn !== undefined);
    const [titleCell, ...restCells] = fieldCells;

    return (
        <div
            data-testid="entity-card"
            data-state={row.getIsSelected() ? "selected" : undefined}
            onClick={() => onRowClick?.(row.original)}
            className={cn(
                "flex flex-col gap-3 p-4 rounded-xl border border-border bg-card",
                "data-[state=selected]:border-primary/50 data-[state=selected]:bg-primary/[0.04]",
                onRowClick && "cursor-pointer active:scale-[0.995] transition-transform",
                className,
            )}
        >
            <div className="flex items-center gap-3 min-w-0">
                {selectCell && (
                    <div onClick={(e) => e.stopPropagation()} className="shrink-0">
                        {flexRender(
                            selectCell.column.columnDef.cell,
                            selectCell.getContext(),
                        )}
                    </div>
                )}
                {titleCell && (
                    <div className="font-medium truncate min-w-0 flex-1">
                        {flexRender(
                            titleCell.column.columnDef.cell,
                            titleCell.getContext(),
                        )}
                    </div>
                )}
            </div>

            {restCells.length > 0 && (
                <dl className="flex flex-col gap-2">
                    {restCells.map((cell) => (
                        <div
                            key={cell.id}
                            className="flex items-start justify-between gap-3"
                        >
                            <dt className={CELL_LABEL}>
                                <ColumnLabelModeContext.Provider value={true}>
                                    {flexRender(
                                        cell.column.columnDef.header,
                                        cell.getContext() as never,
                                    )}
                                </ColumnLabelModeContext.Provider>
                            </dt>
                            <dd className="text-sm text-right min-w-0 break-words">
                                {flexRender(
                                    cell.column.columnDef.cell,
                                    cell.getContext(),
                                )}
                            </dd>
                        </div>
                    ))}
                </dl>
            )}

            {displayCells.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border/60">
                    {displayCells.map((cell) => (
                        <div key={cell.id} className="pt-2">
                            {flexRender(
                                cell.column.columnDef.cell,
                                cell.getContext(),
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

const CardsSkeleton = () => (
    <>
        {Array.from({ length: 4 }).map((_, i) => (
            <div
                key={`entity-card-skeleton-${i}`}
                className="flex flex-col gap-3 p-4 rounded-xl border border-border bg-card"
            >
                <Skeleton className="h-5 w-1/2" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
            </div>
        ))}
    </>
);

export function EntityCards<TData>({
    onRowClick,
    getRowClassName,
}: Readonly<{
    onRowClick?: (object: TData) => void;
    getRowClassName?: (original: TData) => string | undefined;
}>) {
    const { t } = useTranslation();
    const { table, isLoading, isError, refetch } = useEntityTableContext();

    if (isError) {
        return (
            <div className="flex flex-col items-center justify-center gap-3 p-8 text-muted-foreground">
                <AlertCircle className="size-8 text-destructive" />
                <p className="text-sm font-medium">{t("table.error")}</p>
                <Button variant="outline" size="sm" onClick={() => refetch()}>
                    <RefreshCw className="size-4 mr-2" />
                    {t("retry")}
                </Button>
            </div>
        );
    }

    const rows = table.getRowModel().rows;

    return (
        <div className="flex flex-col gap-2 p-2">
            {isLoading ? (
                <CardsSkeleton />
            ) : rows?.length ? (
                rows.map((row: Row<TData>) => (
                    <RowCard
                        key={row.id}
                        row={row}
                        onRowClick={onRowClick}
                        className={getRowClassName?.(row.original)}
                    />
                ))
            ) : (
                <p className="py-10 text-center text-sm text-muted-foreground">
                    {t("table.no-result")}
                </p>
            )}
        </div>
    );
}

export const EntityCardsFallback: FC = () => <CardsSkeleton />;

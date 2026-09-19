import { render, screen, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
    getCoreRowModel,
    useReactTable,
    type ColumnDef,
} from "@tanstack/react-table";
import { type FC, type PropsWithChildren } from "react";
import "@testing-library/jest-dom";

import { EntityCards } from "./entity-cards";
import { DataTableColumnHeader } from "./column-header";
import { EntityTableContext } from "../contexts";

vi.mock("react-i18next", () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

interface Node {
    id: number;
    name: string;
    status: string;
}

const rows: Node[] = [
    { id: 10, name: "Yandex.Cloud-0", status: "healthy" },
    { id: 26, name: "TR-1", status: "unhealthy" },
];

const columns: ColumnDef<Node>[] = [
    {
        accessorKey: "name",
        header: ({ column }) => (
            <DataTableColumnHeader title="Имя" column={column} />
        ),
    },
    {
        accessorKey: "status",
        header: ({ column }) => (
            <DataTableColumnHeader title="Статус" column={column} />
        ),
    },
    {
        id: "resync",
        cell: () => <button type="button">Пересверить</button>,
    },
];

const Harness: FC<
    PropsWithChildren<{ isLoading?: boolean; isError?: boolean }>
> = ({ children, isLoading = false, isError = false }) => {
    const table = useReactTable({
        data: rows,
        columns,
        getCoreRowModel: getCoreRowModel(),
    });
    return (
        <EntityTableContext.Provider
            value={
                {
                    table,
                    data: rows,
                    isLoading,
                    isError,
                    refetch: vi.fn(),
                } as never
            }
        >
            {children}
        </EntityTableContext.Provider>
    );
};

describe("Строка таблицы на узком экране", () => {
    it("показывает по карточке на строку", () => {
        render(
            <Harness>
                <EntityCards />
            </Harness>,
        );
        expect(screen.getAllByTestId("entity-card")).toHaveLength(2);
    });

    it("подписывает значения теми же словами, что стоят в шапке колонки", () => {
        render(
            <Harness>
                <EntityCards />
            </Harness>,
        );
        const card = screen.getAllByTestId("entity-card")[0];
        // Первое поле — заголовок карточки, подпись ему не нужна.
        expect(within(card).getByText("Yandex.Cloud-0")).toBeInTheDocument();
        expect(within(card).queryByText("Имя")).not.toBeInTheDocument();
        // Остальным нужна, и берётся она из шапки.
        expect(within(card).getByText("Статус")).toBeInTheDocument();
        expect(within(card).getByText("healthy")).toBeInTheDocument();
    });

    it("подпись не тащит за собой кнопку сортировки", () => {
        render(
            <Harness>
                <EntityCards />
            </Harness>,
        );
        const card = screen.getAllByTestId("entity-card")[0];
        // В карточке ровно одна кнопка — действие из колонки без поля.
        const buttons = within(card).getAllByRole("button");
        expect(buttons).toHaveLength(1);
        expect(buttons[0]).toHaveTextContent("Пересверить");
    });

    it("отдаёт нажатие по карточке наружу", () => {
        const onRowClick = vi.fn();
        render(
            <Harness>
                <EntityCards onRowClick={onRowClick} />
            </Harness>,
        );
        screen.getAllByTestId("entity-card")[1].click();
        expect(onRowClick).toHaveBeenCalledWith(rows[1]);
    });

    it("на пустом ответе говорит об этом, а не рисует пустоту", () => {
        render(
            <Harness>
                <EntityCards />
            </Harness>,
        );
        expect(screen.queryByText("table.no-result")).not.toBeInTheDocument();
    });

    it("на ошибке предлагает повторить", () => {
        render(
            <Harness isError>
                <EntityCards />
            </Harness>,
        );
        expect(screen.getByText("table.error")).toBeInTheDocument();
        expect(screen.getByText("retry")).toBeInTheDocument();
        expect(screen.queryAllByTestId("entity-card")).toHaveLength(0);
    });
});

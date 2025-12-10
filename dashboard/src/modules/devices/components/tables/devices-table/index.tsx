import type { FC } from "react";
import { useState } from "react";
import { useUserDevicesQuery, DeviceType } from "@marzneshin/modules/devices";
import { columns as columnsFn } from "./columns";
import {
    Table,
    TableHeader,
    TableBody,
    TableRow,
    TableHead,
    TableCell,
    Loading,
} from "@marzneshin/common/components";
import { flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { DeviceDetailDialog } from "../../dialogs/device-detail";
import { DeviceEditDialog } from "../../dialogs/device-edit";
import { DeviceDeleteDialog } from "../../dialogs/device-delete";

interface DevicesTableProps {
    userId: number | string;
}

export const DevicesTable: FC<DevicesTableProps> = ({ userId }) => {
    const [selectedDevice, setSelectedDevice] = useState<DeviceType | null>(null);
    const [detailOpen, setDetailOpen] = useState(false);
    const [editOpen, setEditOpen] = useState(false);
    const [deleteOpen, setDeleteOpen] = useState(false);

    const { data, isLoading } = useUserDevicesQuery(userId, {
        page: 1,
        size: 100,
    });

    const onOpen = (device: DeviceType) => {
        setSelectedDevice(device);
        setDetailOpen(true);
    };

    const onEdit = (device: DeviceType) => {
        setSelectedDevice(device);
        setEditOpen(true);
    };

    const onDelete = (device: DeviceType) => {
        setSelectedDevice(device);
        setDeleteOpen(true);
    };

    const columns = columnsFn({ onEdit, onDelete, onOpen });

    const table = useReactTable({
        data: data?.entities || [],
        columns,
        getCoreRowModel: getCoreRowModel(),
    });

    if (isLoading) {
        return <Loading />;
    }

    return (
        <>
            <div className="w-full overflow-x-auto max-w-full">
                <div className="rounded-md border">
                    <Table className="min-w-full">
                        <TableHeader>
                            {table.getHeaderGroups().map((headerGroup) => (
                                <TableRow key={headerGroup.id}>
                                    {headerGroup.headers.map((header) => (
                                        <TableHead key={header.id}>
                                            {header.isPlaceholder
                                                ? null
                                                : flexRender(
                                                    header.column.columnDef.header,
                                                    header.getContext()
                                                )}
                                        </TableHead>
                                    ))}
                                </TableRow>
                            ))}
                        </TableHeader>
                        <TableBody>
                            {table.getRowModel().rows?.length ? (
                                table.getRowModel().rows.map((row) => (
                                    <TableRow key={row.id}>
                                        {row.getVisibleCells().map((cell) => (
                                            <TableCell key={cell.id}>
                                                {flexRender(
                                                    cell.column.columnDef.cell,
                                                    cell.getContext()
                                                )}
                                            </TableCell>
                                        ))}
                                    </TableRow>
                                ))
                            ) : (
                                <TableRow>
                                    <TableCell
                                        colSpan={columns.length}
                                        className="h-24 text-center"
                                    >
                                        No devices found.
                                    </TableCell>
                                </TableRow>
                            )}
                        </TableBody>
                    </Table>
                </div>
            </div>
            
            {selectedDevice && (
                <>
                    <DeviceDetailDialog
                        open={detailOpen}
                        onOpenChange={setDetailOpen}
                        userId={userId}
                        deviceId={selectedDevice.id}
                    />
                    <DeviceEditDialog
                        open={editOpen}
                        onOpenChange={setEditOpen}
                        userId={userId}
                        device={selectedDevice}
                    />
                    <DeviceDeleteDialog
                        open={deleteOpen}
                        onOpenChange={setDeleteOpen}
                        userId={userId}
                        device={selectedDevice}
                    />
                </>
            )}
        </>
    );
};


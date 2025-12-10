import type { FC } from "react";
import { useState } from "react";
import { useUserDevicesQuery, DeviceType } from "@marzneshin/modules/devices";
import { columns as columnsFn } from "./columns";
import { DataTable } from "@marzneshin/common/components";
import { DeviceDetailDialog } from "../../dialogs/device-detail";
import { DeviceEditDialog } from "../../dialogs/device-edit";
import { DeviceDeleteDialog } from "../../dialogs/device-delete";

interface DevicesTableProps {
    userId: number;
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

    return (
        <>
            <DataTable
                columns={columns}
                data={data?.entities || []}
                isLoading={isLoading}
            />
            
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


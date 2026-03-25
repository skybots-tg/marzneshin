import type { FC } from "react";
import { DoubleEntityTable } from "@marzneshin/libs/entity-table";
import { fetchNodeDevices, NodeDevicesQueryKey } from "../api";
import { nodeDeviceColumns } from "./columns";
import type { DeviceInfoWithUser } from "../types";

interface AllDevicesListProps {
    nodeId: number;
}

export const AllDevicesList: FC<AllDevicesListProps> = ({ nodeId }) => {
    return (
        <DoubleEntityTable<DeviceInfoWithUser>
            fetchEntity={fetchNodeDevices}
            columns={nodeDeviceColumns}
            entityKey={NodeDevicesQueryKey}
            entityId={nodeId}
            primaryFilter="search"
            defaultPageSize={50}
        />
    );
};

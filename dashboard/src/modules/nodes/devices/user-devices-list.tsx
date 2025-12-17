import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { DeviceCard } from "./device-card";
import { useUserDevicesQuery } from "../api";
import { Loader2, AlertCircle } from "lucide-react";
import {
    Alert,
    AlertDescription,
    AlertTitle,
} from "@marzneshin/common/components/ui/alert";
import { Switch } from "@marzneshin/common/components/ui/switch";
import { Label } from "@marzneshin/common/components/ui/label";

interface UserDevicesListProps {
    nodeId: number;
    userId: number;
}

export const UserDevicesList: FC<UserDevicesListProps> = ({ nodeId, userId }) => {
    const { t } = useTranslation();
    const [activeOnly, setActiveOnly] = useState(false);
    
    const { data, isLoading, error } = useUserDevicesQuery({
        nodeId,
        userId,
        activeOnly,
    });

    if (isLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
        );
    }

    if (error) {
        return (
            <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>{t("error")}</AlertTitle>
                <AlertDescription>
                    {t("page.nodes.devices.error_loading")}
                </AlertDescription>
            </Alert>
        );
    }

    const devices = data?.devices || [];

    return (
        <div className="space-y-4">
            {/* Filter Controls */}
            <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                    <Switch
                        id="active-only"
                        checked={activeOnly}
                        onCheckedChange={setActiveOnly}
                    />
                    <Label htmlFor="active-only">
                        {t("page.nodes.devices.active_only")}
                    </Label>
                </div>
                <div className="text-sm text-muted-foreground">
                    {t("page.nodes.devices.total_devices", { count: devices.length })}
                </div>
            </div>

            {/* Devices List */}
            {devices.length === 0 ? (
                <Alert>
                    <AlertDescription>
                        {activeOnly
                            ? t("page.nodes.devices.no_active_devices")
                            : t("page.nodes.devices.no_devices")}
                    </AlertDescription>
                </Alert>
            ) : (
                <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
                    {devices.map((device, index) => (
                        <DeviceCard
                            key={`${device.remote_ip}-${device.client_name}-${index}`}
                            device={device}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};


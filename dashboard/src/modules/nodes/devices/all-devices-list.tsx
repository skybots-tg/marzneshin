import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { DeviceCard } from "./device-card";
import { useAllDevicesQuery } from "../api";
import { Loader2, AlertCircle, User, ChevronDown, ChevronRight } from "lucide-react";
import {
    Alert,
    AlertDescription,
    AlertTitle,
} from "@marzneshin/common/components/ui/alert";
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@marzneshin/common/components/ui/collapsible";
import { Button } from "@marzneshin/common/components/ui/button";
import { Badge } from "@marzneshin/common/components/ui/badge";

interface AllDevicesListProps {
    nodeId: number;
}

type FilterMode = 'all' | 'active';

export const AllDevicesList: FC<AllDevicesListProps> = ({ nodeId }) => {
    const { t } = useTranslation();
    const { data, isLoading, error } = useAllDevicesQuery({ nodeId });
    const [expandedUsers, setExpandedUsers] = useState<Set<number>>(new Set());
    const [filterMode, setFilterMode] = useState<FilterMode>('all');

    const toggleUser = (userId: number) => {
        setExpandedUsers((prev) => {
            const next = new Set(prev);
            if (next.has(userId)) {
                next.delete(userId);
            } else {
                next.add(userId);
            }
            return next;
        });
    };

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

    const users = data?.users || [];
    const totalDevices = users.reduce((sum, user) => sum + user.devices.length, 0);
    const activeDevices = users.reduce(
        (sum, user) => sum + user.devices.filter((d) => d.is_active).length,
        0
    );

    // Filter users based on filter mode
    const filteredUsers = users.map(user => ({
        ...user,
        devices: filterMode === 'active' 
            ? user.devices.filter(d => d.is_active)
            : user.devices
    })).filter(user => user.devices.length > 0);

    return (
        <div className="space-y-4">
            {/* Summary */}
            <div className="flex items-center gap-4 text-sm">
                <Badge 
                    variant="outline"
                    className="cursor-pointer hover:bg-accent"
                    onClick={() => setFilterMode('all')}
                >
                    {t("page.nodes.devices.total_users", { count: users.length })}
                </Badge>
                <Badge 
                    variant={filterMode === 'all' ? 'default' : 'outline'}
                    className="cursor-pointer hover:bg-accent"
                    onClick={() => setFilterMode('all')}
                >
                    {t("page.nodes.devices.total_devices", { count: totalDevices })}
                </Badge>
                <Badge 
                    variant={filterMode === 'active' ? 'default' : 'outline'}
                    className="cursor-pointer hover:bg-accent"
                    onClick={() => setFilterMode('active')}
                >
                    {t("page.nodes.devices.active_devices", { count: activeDevices })}
                </Badge>
            </div>

            {/* Users List */}
            {filteredUsers.length === 0 ? (
                <Alert>
                    <AlertDescription>
                        {filterMode === 'active' 
                            ? t("page.nodes.devices.no_active_devices")
                            : t("page.nodes.devices.no_devices")}
                    </AlertDescription>
                </Alert>
            ) : (
                <div className="space-y-2">
                    {filteredUsers.map((userDevices) => {
                        const activeCount = userDevices.devices.filter((d) => d.is_active).length;
                        const isExpanded = expandedUsers.has(userDevices.uid);

                        return (
                            <Collapsible
                                key={userDevices.uid}
                                open={isExpanded}
                                onOpenChange={() => toggleUser(userDevices.uid)}
                            >
                                <CollapsibleTrigger asChild>
                                    <Button
                                        variant="outline"
                                        className="w-full justify-between"
                                    >
                                        <div className="flex items-center gap-2">
                                            {isExpanded ? (
                                                <ChevronDown className="h-4 w-4" />
                                            ) : (
                                                <ChevronRight className="h-4 w-4" />
                                            )}
                                            <User className="h-4 w-4" />
                                            <span>
                                                {t("page.nodes.devices.user_id", {
                                                    id: userDevices.uid,
                                                })}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <Badge variant="secondary">
                                                {userDevices.devices.length} {t("devices")}
                                            </Badge>
                                            <Badge variant="default">
                                                {activeCount} {t("active")}
                                            </Badge>
                                        </div>
                                    </Button>
                                </CollapsibleTrigger>
                                <CollapsibleContent className="pt-4">
                                    <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 pl-4">
                                        {userDevices.devices.map((device, index) => (
                                            <DeviceCard
                                                key={`${device.remote_ip}-${device.client_name}-${index}`}
                                                device={device}
                                            />
                                        ))}
                                    </div>
                                </CollapsibleContent>
                            </Collapsible>
                        );
                    })}
                </div>
            )}
        </div>
    );
};


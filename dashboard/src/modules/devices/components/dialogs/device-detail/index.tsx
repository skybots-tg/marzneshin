import type { FC } from "react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    ScrollArea,
    VStack,
    Badge,
    Separator,
    Loading,
} from "@marzneshin/common/components";
import { useDeviceDetailQuery } from "@marzneshin/modules/devices";
import { formatDistanceToNow } from "date-fns";
import { Smartphone, MapPin, Activity, HardDrive } from "lucide-react";

interface DeviceDetailDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    userId: number;
    deviceId: number;
}

const formatBytes = (bytes?: number) => {
    if (!bytes) return "0 B";
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`;
};

export const DeviceDetailDialog: FC<DeviceDetailDialogProps> = ({
    open,
    onOpenChange,
    userId,
    deviceId,
}) => {
    const { data: device, isLoading } = useDeviceDetailQuery(userId, deviceId);

    if (isLoading || !device) {
        return (
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent>
                    <Loading />
                </DialogContent>
            </Dialog>
        );
    }

    const totalTraffic = (device.total_upload_bytes || 0) + (device.total_download_bytes || 0);
    const uniqueCountries = [...new Set(device.ips.map(ip => ip.country_code).filter(Boolean))];

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Smartphone className="w-5 h-5" />
                        {device.display_name || device.client_name || "Device Details"}
                    </DialogTitle>
                </DialogHeader>
                
                <ScrollArea className="max-h-[600px]">
                    <VStack className="gap-4 p-4">
                        {/* Basic Info */}
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <p className="text-sm text-muted-foreground">Client</p>
                                <p className="font-medium">{device.client_name || "Unknown"}</p>
                            </div>
                            <div>
                                <p className="text-sm text-muted-foreground">Type</p>
                                <Badge>{device.client_type}</Badge>
                            </div>
                            <div>
                                <p className="text-sm text-muted-foreground">First Seen</p>
                                <p className="text-sm">
                                    {formatDistanceToNow(new Date(device.first_seen_at), { addSuffix: true })}
                                </p>
                            </div>
                            <div>
                                <p className="text-sm text-muted-foreground">Last Seen</p>
                                <p className="text-sm">
                                    {formatDistanceToNow(new Date(device.last_seen_at), { addSuffix: true })}
                                </p>
                            </div>
                            <div>
                                <p className="text-sm text-muted-foreground">Status</p>
                                {device.is_blocked ? (
                                    <Badge variant="destructive">Blocked</Badge>
                                ) : (
                                    <Badge variant="default" className="bg-green-500/20 text-green-700">Active</Badge>
                                )}
                            </div>
                            <div>
                                <p className="text-sm text-muted-foreground">Trust Level</p>
                                <Badge>{device.trust_level > 0 ? "+" : ""}{device.trust_level}</Badge>
                            </div>
                        </div>

                        <Separator />

                        {/* Traffic Stats */}
                        <div className="space-y-2">
                            <div className="flex items-center gap-2">
                                <Activity className="w-4 h-4" />
                                <h3 className="font-semibold">Traffic Statistics</h3>
                            </div>
                            <div className="grid grid-cols-3 gap-4">
                                <div className="p-3 bg-muted/50 rounded-lg">
                                    <p className="text-xs text-muted-foreground">Upload</p>
                                    <p className="font-medium">{formatBytes(device.total_upload_bytes)}</p>
                                </div>
                                <div className="p-3 bg-muted/50 rounded-lg">
                                    <p className="text-xs text-muted-foreground">Download</p>
                                    <p className="font-medium">{formatBytes(device.total_download_bytes)}</p>
                                </div>
                                <div className="p-3 bg-muted/50 rounded-lg">
                                    <p className="text-xs text-muted-foreground">Total</p>
                                    <p className="font-medium">{formatBytes(totalTraffic)}</p>
                                </div>
                            </div>
                        </div>

                        <Separator />

                        {/* IP Addresses */}
                        <div className="space-y-2">
                            <div className="flex items-center gap-2">
                                <MapPin className="w-4 h-4" />
                                <h3 className="font-semibold">IP Addresses ({device.ips.length})</h3>
                            </div>
                            {uniqueCountries.length > 0 && (
                                <div className="flex gap-2 flex-wrap">
                                    {uniqueCountries.map(country => (
                                        <Badge key={country} variant="outline">
                                            {country}
                                        </Badge>
                                    ))}
                                </div>
                            )}
                            <div className="space-y-2 mt-2">
                                {device.ips.slice(0, 10).map((ip) => (
                                    <div key={ip.id} className="flex items-center justify-between p-2 bg-muted/30 rounded">
                                        <div className="flex items-center gap-3">
                                            <HardDrive className="w-4 h-4" />
                                            <div>
                                                <p className="font-mono text-sm">{ip.ip}</p>
                                                {ip.country_code && (
                                                    <p className="text-xs text-muted-foreground">
                                                        {ip.country_code} {ip.city && `• ${ip.city}`}
                                                        {ip.is_datacenter && " • Datacenter"}
                                                    </p>
                                                )}
                                            </div>
                                        </div>
                                        <div className="text-right">
                                            <p className="text-sm">{formatBytes(ip.upload_bytes + ip.download_bytes)}</p>
                                            <p className="text-xs text-muted-foreground">{ip.connect_count} connections</p>
                                        </div>
                                    </div>
                                ))}
                                {device.ips.length > 10 && (
                                    <p className="text-sm text-muted-foreground text-center">
                                        ... and {device.ips.length - 10} more IPs
                                    </p>
                                )}
                            </div>
                        </div>
                    </VStack>
                </ScrollArea>
            </DialogContent>
        </Dialog>
    );
};


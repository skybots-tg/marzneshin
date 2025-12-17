import { FC } from "react";
import { useTranslation } from "react-i18next";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@marzneshin/common/components/ui";
import { Badge } from "@marzneshin/common/components/ui/badge";
import {
    Monitor,
    Globe,
    Activity,
    ArrowUpDown,
    ArrowUp,
    ArrowDown,
    Clock,
} from "lucide-react";
import type { DeviceInfo } from "../types";

interface DeviceCardProps {
    device: DeviceInfo;
}

const formatBytes = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${Number.parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

const formatDate = (timestamp: number): string => {
    return new Date(timestamp * 1000).toLocaleString();
};

export const DeviceCard: FC<DeviceCardProps> = ({ device }) => {
    const { t } = useTranslation();

    return (
        <Card className="w-full">
            <CardHeader>
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Monitor className="h-5 w-5" />
                        <CardTitle className="text-lg">{device.client_name}</CardTitle>
                    </div>
                    <Badge variant={device.is_active ? "default" : "secondary"}>
                        <Activity className="h-3 w-3 mr-1" />
                        {device.is_active ? t("active") : t("inactive")}
                    </Badge>
                </div>
                <CardDescription className="flex items-center gap-1">
                    <Globe className="h-4 w-4" />
                    {device.remote_ip}
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
                {/* Protocol and User Agent */}
                {(device.protocol || device.user_agent) && (
                    <div className="flex flex-wrap gap-2">
                        {device.protocol && (
                            <Badge variant="outline">
                                {t("protocol")}: {device.protocol}
                            </Badge>
                        )}
                        {device.user_agent && (
                            <Badge variant="outline" className="max-w-xs truncate">
                                {device.user_agent}
                            </Badge>
                        )}
                        {device.tls_fingerprint && (
                            <Badge variant="outline">
                                TLS: {device.tls_fingerprint}
                            </Badge>
                        )}
                    </div>
                )}

                {/* Traffic Stats */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                    <div className="flex items-center gap-2 p-2 rounded-md bg-muted/50">
                        <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
                        <div>
                            <div className="text-xs text-muted-foreground">{t("total")}</div>
                            <div className="font-semibold">{formatBytes(device.total_usage)}</div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2 p-2 rounded-md bg-muted/50">
                        <ArrowUp className="h-4 w-4 text-blue-500" />
                        <div>
                            <div className="text-xs text-muted-foreground">{t("upload")}</div>
                            <div className="font-semibold">{formatBytes(device.uplink)}</div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2 p-2 rounded-md bg-muted/50">
                        <ArrowDown className="h-4 w-4 text-green-500" />
                        <div>
                            <div className="text-xs text-muted-foreground">{t("download")}</div>
                            <div className="font-semibold">{formatBytes(device.downlink)}</div>
                        </div>
                    </div>
                </div>

                {/* Timestamps */}
                <div className="flex flex-col sm:flex-row gap-2 text-xs text-muted-foreground">
                    <div className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        <span>{t("first_seen")}: {formatDate(device.first_seen)}</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        <span>{t("last_seen")}: {formatDate(device.last_seen)}</span>
                    </div>
                </div>
            </CardContent>
        </Card>
    );
};


import type { FC } from "react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
    DialogDescription,
    Button,
} from "@marzneshin/common/components";
import { useDevicesDeleteMutation, DeviceType } from "@marzneshin/modules/devices";
import { AlertTriangle } from "lucide-react";

interface DeviceDeleteDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    userId: number | string;
    device: DeviceType;
}

export const DeviceDeleteDialog: FC<DeviceDeleteDialogProps> = ({
    open,
    onOpenChange,
    userId,
    device,
}) => {
    const deleteMutation = useDevicesDeleteMutation();

    const handleDelete = () => {
        deleteMutation.mutate({
            userId,
            deviceId: device.id,
        }, {
            onSuccess: () => {
                onOpenChange(false);
            },
        });
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <div className="flex items-center gap-2">
                        <AlertTriangle className="w-5 h-5 text-destructive" />
                        <DialogTitle>Delete Device</DialogTitle>
                    </div>
                    <DialogDescription>
                        Are you sure you want to delete this device? This action cannot be undone.
                        All device history and statistics will be permanently removed.
                    </DialogDescription>
                </DialogHeader>

                <div className="py-4">
                    <div className="p-4 bg-muted/50 rounded-lg">
                        <p className="font-medium">
                            {device.display_name || device.client_name || "Unknown Device"}
                        </p>
                        <p className="text-sm text-muted-foreground">
                            {device.client_type} • {device.ip_count || 0} IP addresses
                        </p>
                    </div>
                </div>

                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        disabled={deleteMutation.isPending}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive"
                        onClick={handleDelete}
                        disabled={deleteMutation.isPending}
                    >
                        {deleteMutation.isPending ? "Deleting..." : "Delete Device"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};


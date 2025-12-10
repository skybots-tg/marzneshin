import type { FC } from "react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
    Button,
    Form,
    FormField,
    FormItem,
    FormLabel,
    FormControl,
    FormMessage,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    VStack,
} from "@marzneshin/common/components";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { DeviceSchema, DeviceMutationType, DeviceType } from "@marzneshin/modules/devices";
import { useDevicesUpdateMutation } from "@marzneshin/modules/devices";

interface DeviceEditDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    userId: number;
    device: DeviceType;
}

export const DeviceEditDialog: FC<DeviceEditDialogProps> = ({
    open,
    onOpenChange,
    userId,
    device,
}) => {
    const updateMutation = useDevicesUpdateMutation();

    const form = useForm<DeviceMutationType>({
        resolver: zodResolver(DeviceSchema),
        defaultValues: {
            display_name: device.display_name || "",
            is_blocked: device.is_blocked,
            trust_level: device.trust_level,
        },
    });

    const onSubmit = (data: DeviceMutationType) => {
        updateMutation.mutate({
            userId,
            deviceId: device.id,
            data,
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
                    <DialogTitle>Edit Device</DialogTitle>
                </DialogHeader>
                
                <Form {...form}>
                    <form onSubmit={form.handleSubmit(onSubmit)}>
                        <VStack className="gap-4">
                            <FormField
                                control={form.control}
                                name="display_name"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>Display Name</FormLabel>
                                        <FormControl>
                                            <Input 
                                                placeholder="My Phone" 
                                                {...field} 
                                                value={field.value || ""}
                                            />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            <FormField
                                control={form.control}
                                name="trust_level"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>Trust Level</FormLabel>
                                        <Select
                                            onValueChange={(value) => field.onChange(parseInt(value))}
                                            defaultValue={field.value?.toString()}
                                        >
                                            <FormControl>
                                                <SelectTrigger>
                                                    <SelectValue placeholder="Select trust level" />
                                                </SelectTrigger>
                                            </FormControl>
                                            <SelectContent>
                                                <SelectItem value="-1">Suspicious (-1)</SelectItem>
                                                <SelectItem value="0">Normal (0)</SelectItem>
                                                <SelectItem value="1">Trusted (+1)</SelectItem>
                                                <SelectItem value="2">Highly Trusted (+2)</SelectItem>
                                            </SelectContent>
                                        </Select>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            <FormField
                                control={form.control}
                                name="is_blocked"
                                render={({ field }) => (
                                    <FormItem className="flex items-center justify-between rounded-lg border p-4">
                                        <div className="space-y-0.5">
                                            <FormLabel className="text-base">Block Device</FormLabel>
                                            <div className="text-sm text-muted-foreground">
                                                Prevent this device from connecting
                                            </div>
                                        </div>
                                        <FormControl>
                                            <Switch
                                                checked={field.value}
                                                onCheckedChange={field.onChange}
                                            />
                                        </FormControl>
                                    </FormItem>
                                )}
                            />
                        </VStack>

                        <DialogFooter className="mt-4">
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => onOpenChange(false)}
                            >
                                Cancel
                            </Button>
                            <Button 
                                type="submit"
                                disabled={updateMutation.isPending}
                            >
                                {updateMutation.isPending ? "Saving..." : "Save Changes"}
                            </Button>
                        </DialogFooter>
                    </form>
                </Form>
            </DialogContent>
        </Dialog>
    );
};


import { z } from "zod";

export const DeviceSchema = z.object({
    display_name: z.string().max(64).nullable().optional(),
    is_blocked: z.boolean().optional(),
    trust_level: z.number().int().min(-100).max(100).optional(),
});

export type DeviceMutationType = z.infer<typeof DeviceSchema>;


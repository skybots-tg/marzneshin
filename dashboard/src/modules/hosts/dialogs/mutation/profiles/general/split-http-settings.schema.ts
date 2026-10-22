import { z } from "zod";
import { XMuxSettingsSchema } from "./x-mux-settings.schema";

export const splitHttpSettingsModes = ["auto", "packet-up", "stream-up", "stream-one"]

export const SplitHttpSettingsSchema = z.object({
    mode: z.enum(["auto", "packet-up", "stream-up", "stream-one"]).nullable().optional(),
    no_grpc_header: z.boolean().nullable().optional(),
    padding_bytes: z.string().nullable().optional(),
    sc_min_posts_interval_ms: z.string().regex(/^\d{1,10}(-\d{1,10})?$/).nullable().optional(),
    sc_max_each_post_bytes: z.string().regex(/^\d{1,10}(-\d{1,10})?$/).nullable().optional(),
    xmux: XMuxSettingsSchema.nullable().optional(),
    max_retries: z.number().nullable().optional(),
    timeout: z.string().nullable().optional(),
});

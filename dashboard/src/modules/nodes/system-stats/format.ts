/**
 * Tiny human-friendly formatters for the node system-stats widget.
 *
 * Keeping these in their own module so the cell component itself
 * stays under the modular-development limit and the formatters are
 * easy to reuse from a future "node detail" page.
 */

const KIB = 1024;
const MIB = KIB * 1024;
const GIB = MIB * 1024;
const TIB = GIB * 1024;

export const formatBytes = (bytes: number, fractionDigits = 1): string => {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    if (bytes >= TIB) return `${(bytes / TIB).toFixed(fractionDigits)} TB`;
    if (bytes >= GIB) return `${(bytes / GIB).toFixed(fractionDigits)} GB`;
    if (bytes >= MIB) return `${(bytes / MIB).toFixed(fractionDigits)} MB`;
    if (bytes >= KIB) return `${(bytes / KIB).toFixed(fractionDigits)} KB`;
    return `${bytes} B`;
};

export const formatPercent = (value: number): string => {
    if (!Number.isFinite(value)) return "—";
    return `${Math.max(0, Math.min(100, value)).toFixed(0)}%`;
};

export const formatUptime = (seconds: number): string => {
    if (!Number.isFinite(seconds) || seconds <= 0) return "—";
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
};

/**
 * Map a 0-100 utilisation percent to a tailwind text colour. Used for
 * both the inline number and the progress bar tint so the user can
 * see at a glance which resource is hot.
 */
export const utilizationColor = (
    pct: number
): { text: string; bar: string } => {
    if (!Number.isFinite(pct)) return { text: "text-muted-foreground", bar: "bg-muted" };
    if (pct >= 90) return { text: "text-destructive", bar: "bg-destructive" };
    if (pct >= 75) return { text: "text-amber-500", bar: "bg-amber-500" };
    return { text: "text-emerald-500", bar: "bg-emerald-500" };
};

import { Badge, Card, CardContent } from "@marzneshin/common/components";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import type { MatrixCell } from "./api";

type Grid = Record<string, Record<string, MatrixCell>>;

/** Cell state, ordered by how much attention it needs. */
const cellState = (c?: MatrixCell) => {
    if (!c) return "absent";
    if (c.pass > 0) return c.enabled > 0 ? "ok" : "ok-hidden";
    if (c.wrong_geo > 0) return "geo";
    if (c.skip > 0) return "skip";
    return c.enabled > 0 ? "dead" : "dead-hidden";
};

const STATE_STYLE: Record<string, string> = {
    ok: "bg-green-500/15 text-green-600 dark:text-green-400",
    "ok-hidden": "bg-green-500/10 text-green-600/60 dark:text-green-400/60",
    geo: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
    dead: "bg-red-500/20 text-red-600 dark:text-red-400 font-semibold",
    "dead-hidden": "text-muted-foreground/40",
    skip: "text-muted-foreground/60",
    absent: "text-muted-foreground/25",
};

const STATE_GLYPH: Record<string, string> = {
    ok: "OK",
    "ok-hidden": "ok",
    geo: "GEO",
    dead: "DEAD",
    "dead-hidden": "–",
    skip: "?",
    absent: "·",
};

const sortEntries = (keys: string[]) =>
    [...keys].sort((a, b) => {
        const [ta, ia] = a.split("-");
        const [tb, ib] = b.split("-");
        return ta === tb ? Number(ia) - Number(ib) : ta.localeCompare(tb);
    });

export const BridgeMatrix: FC<{ matrix: Grid }> = ({ matrix }) => {
    const { t } = useTranslation();
    const entries = sortEntries(Object.keys(matrix));
    const slots = [
        ...new Set(entries.flatMap((e) => Object.keys(matrix[e]))),
    ].sort();

    if (!entries.length) return null;

    return (
        <Card>
            <CardContent className="p-0 overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                    <thead>
                        <tr className="border-b">
                            <th className="text-left p-2 sticky left-0 bg-card">
                                {t("page.bridge_health.entry")}
                            </th>
                            {slots.map((s) => (
                                <th key={s} className="p-2 text-center text-xs font-medium">
                                    {s}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {entries.map((ek) => (
                            <tr key={ek} className="border-b hover:bg-muted/30">
                                <td className="p-2 sticky left-0 bg-card whitespace-nowrap">
                                    <Badge variant="default">{ek.toUpperCase()}</Badge>
                                </td>
                                {slots.map((s) => {
                                    const cell = matrix[ek][s];
                                    const state = cellState(cell);
                                    return (
                                        <td
                                            key={s}
                                            className={`p-2 text-center text-xs ${STATE_STYLE[state]}`}
                                            title={
                                                cell
                                                    ? `${t("page.bridge_health.hosts")}: ${cell.host_ids.join(", ")}`
                                                    : t("page.bridge_health.no_host")
                                            }
                                        >
                                            {STATE_GLYPH[state]}
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </CardContent>
        </Card>
    );
};

export const MatrixLegend: FC = () => {
    const { t } = useTranslation();
    const items: [string, string][] = [
        ["ok", t("page.bridge_health.legend.ok")],
        ["ok-hidden", t("page.bridge_health.legend.ok_hidden")],
        ["geo", t("page.bridge_health.legend.geo")],
        ["dead", t("page.bridge_health.legend.dead")],
        ["dead-hidden", t("page.bridge_health.legend.dead_hidden")],
        ["absent", t("page.bridge_health.legend.absent")],
    ];
    return (
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
            {items.map(([state, label]) => (
                <span key={state} className="flex items-center gap-1">
                    <span className={`px-1.5 rounded ${STATE_STYLE[state]}`}>
                        {STATE_GLYPH[state]}
                    </span>
                    {label}
                </span>
            ))}
        </div>
    );
};

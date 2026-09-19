import { type FC } from "react";
import { cn } from "@marzneshin/common/utils";

/**
 * Кольцевой индикатор доли.
 *
 * Заменил `CircularProgress` из NextUI: тот тянул за собой четыре пакета и
 * собственную тему ради двух мест в интерфейсе, из-за чего в панели
 * сосуществовали две системы компонентов с разными токенами и разными
 * скруглениями. Здесь — обычный SVG на тех же переменных, что и всё
 * остальное.
 */

const SIZES = {
    sm: { box: 36, stroke: 3.5, text: "text-[10px]" },
    md: { box: 52, stroke: 4, text: "text-xs" },
    lg: { box: 72, stroke: 5, text: "text-sm" },
} as const;

export interface CircularProgressProps {
    /** Доля в процентах, 0–100. Значения вне диапазона подрезаются. */
    value: number;
    size?: keyof typeof SIZES;
    /** Показать процент в центре кольца. */
    showValueLabel?: boolean;
    /** Цвет заполненной дуги; по умолчанию акцент темы. */
    indicatorClassName?: string;
    className?: string;
    "aria-label"?: string;
}

export const CircularProgress: FC<CircularProgressProps> = ({
    value,
    size = "md",
    showValueLabel = false,
    indicatorClassName,
    className,
    "aria-label": ariaLabel,
}) => {
    const { box, stroke, text } = SIZES[size];
    const safe = Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
    const radius = (box - stroke) / 2;
    const circumference = 2 * Math.PI * radius;
    const center = box / 2;

    return (
        <div
            className={cn("relative shrink-0", className)}
            style={{ width: box, height: box }}
            role="progressbar"
            aria-valuenow={Math.round(safe)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={ariaLabel}
        >
            <svg width={box} height={box} className="-rotate-90">
                <circle
                    cx={center}
                    cy={center}
                    r={radius}
                    fill="none"
                    strokeWidth={stroke}
                    className="stroke-muted"
                />
                <circle
                    cx={center}
                    cy={center}
                    r={radius}
                    fill="none"
                    strokeWidth={stroke}
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    strokeDashoffset={circumference * (1 - safe / 100)}
                    className={cn(
                        "stroke-primary transition-[stroke-dashoffset] duration-500 ease-out",
                        indicatorClassName,
                    )}
                />
            </svg>
            {showValueLabel && (
                <span
                    className={cn(
                        "absolute inset-0 flex items-center justify-center font-medium tabular-nums text-foreground",
                        text,
                    )}
                >
                    {Math.round(safe)}%
                </span>
            )}
        </div>
    );
};

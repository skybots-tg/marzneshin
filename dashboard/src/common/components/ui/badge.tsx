import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@marzneshin/common/utils"

const badgeVariants = cva(
    "inline-flex items-center rounded-full border-2 px-2.5 py-0.5 text-xs font-semibold font-header uppercase tracking-wider transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
    {
        variants: {
            variant: {
                default:
                    "border-primary/35 bg-primary/15 text-primary hover:bg-primary/25 shadow-[0_0_8px_rgba(0,200,200,0.15)] dark:shadow-[0_0_10px_rgba(0,255,255,0.2)]",
                secondary:
                    "border-secondary/35 bg-secondary/15 text-secondary hover:bg-secondary/25 shadow-[0_0_8px_rgba(255,0,255,0.15)] dark:shadow-[0_0_10px_rgba(255,0,255,0.2)]",
                destructive:
                    "border-destructive/35 bg-destructive/15 text-destructive hover:bg-destructive/25 shadow-[0_0_8px_rgba(255,0,100,0.15)] dark:shadow-[0_0_10px_rgba(255,0,100,0.2)]",
                royal:
                    "border-indigo-400/35 bg-indigo-900/15 text-indigo-400 hover:bg-indigo-900/25 shadow-[0_0_8px_rgba(99,102,241,0.15)] dark:text-indigo-300 dark:shadow-[0_0_10px_rgba(99,102,241,0.2)]",
                positive:
                    "border-emerald-400/35 bg-emerald-900/15 text-emerald-500 hover:bg-emerald-900/25 shadow-[0_0_8px_rgba(16,185,129,0.15)] dark:text-emerald-300 dark:shadow-[0_0_10px_rgba(16,185,129,0.2)]",
                disabled:
                    "border-gray-400/35 bg-gray-900/15 text-gray-500 hover:bg-gray-900/25 dark:text-gray-400",
                warning:
                    "border-amber-400/35 bg-amber-900/15 text-amber-500 hover:bg-amber-900/25 shadow-[0_0_8px_rgba(245,158,11,0.15)] dark:text-amber-300 dark:shadow-[0_0_10px_rgba(245,158,11,0.2)]",
                outline: "text-foreground border-primary/25 hover:bg-primary/10",
            },
        },
        defaultVariants: {
            variant: "default",
        },
    }
)

export interface BadgeProps
    extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> { }

function Badge({ className, variant, ...props }: BadgeProps) {
    return (
        <div className={cn(badgeVariants({ variant }), className)} {...props} />
    )
}

type BadgeVariantKeys =
    | 'default'
    | 'secondary'
    | 'destructive'
    | 'royal'
    | 'positive'
    | 'disabled'
    | 'warning'
    | 'outline';

export { Badge, badgeVariants, type BadgeVariantKeys }

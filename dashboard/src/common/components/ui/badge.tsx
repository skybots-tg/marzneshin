import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@marzneshin/common/utils"

const badgeVariants = cva(
    "inline-flex items-center rounded-full border-2 px-2.5 py-0.5 text-xs font-semibold font-header uppercase tracking-wider transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
    {
        variants: {
            variant: {
                default:
                    "border-primary/50 bg-primary/20 text-primary hover:bg-primary/30 shadow-[0_0_10px_rgba(0,255,255,0.2)]",
                secondary:
                    "border-secondary/50 bg-secondary/20 text-secondary hover:bg-secondary/30 shadow-[0_0_10px_rgba(255,0,255,0.2)]",
                destructive:
                    "border-destructive/50 bg-destructive/20 text-destructive hover:bg-destructive/30 shadow-[0_0_10px_rgba(255,0,100,0.2)]",
                royal:
                    "border-indigo-500/50 bg-indigo-900/20 text-indigo-300 hover:bg-indigo-900/30 shadow-[0_0_10px_rgba(99,102,241,0.2)]",
                positive:
                    "border-emerald-500/50 bg-emerald-900/20 text-emerald-300 hover:bg-emerald-900/30 shadow-[0_0_10px_rgba(16,185,129,0.2)]",
                disabled:
                    "border-gray-500/50 bg-gray-900/20 text-gray-400 hover:bg-gray-900/30",
                warning:
                    "border-amber-500/50 bg-amber-900/20 text-amber-300 hover:bg-amber-900/30 shadow-[0_0_10px_rgba(245,158,11,0.2)]",
                outline: "text-foreground border-primary/30",
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

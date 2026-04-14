import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@marzneshin/common/utils"

const badgeVariants = cva(
    "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)] focus:outline-none focus:ring-2 focus:ring-ring/30 focus:ring-offset-2",
    {
        variants: {
            variant: {
                default:
                    "bg-primary/12 text-primary dark:bg-primary/18 dark:text-primary",
                secondary:
                    "bg-secondary text-secondary-foreground",
                destructive:
                    "bg-destructive/12 text-destructive dark:bg-destructive/18",
                royal:
                    "bg-blue-500/12 text-blue-600 dark:bg-blue-400/18 dark:text-blue-400",
                positive:
                    "bg-success/12 text-success dark:bg-success/18",
                disabled:
                    "bg-muted text-muted-foreground opacity-50",
                warning:
                    "bg-warning/12 text-warning dark:bg-warning/18",
                outline: "border border-border/60 bg-transparent text-foreground",
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

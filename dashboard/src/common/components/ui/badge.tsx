import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@marzneshin/common/utils"

const badgeVariants = cva(
    "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-smooth focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
    {
        variants: {
            variant: {
                default:
                    "border-primary/20 bg-primary/10 text-primary hover:bg-primary/15 dark:border-primary/30 dark:bg-primary/15 dark:text-primary",
                secondary:
                    "border-secondary/20 bg-secondary/10 text-secondary-foreground hover:bg-secondary/15 dark:border-secondary/30 dark:bg-secondary/15",
                destructive:
                    "border-destructive/20 bg-destructive/10 text-destructive hover:bg-destructive/15 dark:border-destructive/30 dark:bg-destructive/15 dark:text-destructive",
                royal:
                    "border-blue-500/20 bg-blue-500/10 text-blue-600 hover:bg-blue-500/15 dark:border-blue-400/30 dark:bg-blue-400/15 dark:text-blue-400",
                positive:
                    "border-success/20 bg-success/10 text-success hover:bg-success/15 dark:border-success/30 dark:bg-success/15 dark:text-success",
                disabled:
                    "border-muted/20 bg-muted/10 text-muted-foreground opacity-50",
                warning:
                    "border-warning/20 bg-warning/10 text-warning hover:bg-warning/15 dark:border-warning/30 dark:bg-warning/15 dark:text-warning",
                outline: "border-border bg-transparent text-foreground hover:bg-accent",
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

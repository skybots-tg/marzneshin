import * as React from "react"
import * as TogglePrimitive from "@radix-ui/react-toggle"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@marzneshin/common/utils"

const toggleVariants = cva(
    "inline-flex items-center justify-center rounded-xl text-[13px] font-medium ring-offset-background transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)] hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-0 disabled:pointer-events-none disabled:opacity-40 data-[state=on]:bg-accent/60 data-[state=on]:text-accent-foreground",
    {
        variants: {
            variant: {
                default: "bg-transparent",
                outline:
                    "border border-border/40 bg-transparent hover:bg-secondary hover:text-foreground",
            },
            size: {
                default: "h-10 px-3",
                sm: "h-9 px-2.5",
                lg: "h-11 px-5",
            },
        },
        defaultVariants: {
            variant: "default",
            size: "default",
        },
    }
)

const Toggle = React.forwardRef<
    React.ElementRef<typeof TogglePrimitive.Root>,
    React.ComponentPropsWithoutRef<typeof TogglePrimitive.Root> &
    VariantProps<typeof toggleVariants>
>(({ className, variant, size, ...props }, ref) => (
    <TogglePrimitive.Root
        ref={ref}
        className={cn(toggleVariants({ variant, size, className }))}
        {...props}
    />
))

Toggle.displayName = TogglePrimitive.Root.displayName

export { Toggle, toggleVariants }

import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"

import { cn } from "@marzneshin/common/utils"

const Progress = React.forwardRef<
    React.ElementRef<typeof ProgressPrimitive.Root>,
    React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => (
    <ProgressPrimitive.Root
        ref={ref}
        className={cn(
            "relative h-2 w-full overflow-hidden rounded-full bg-secondary/80 border-[0.5px] border-border/30",
            className
        )}
        {...props}
    >
        <ProgressPrimitive.Indicator
            className="h-full w-full flex-1 bg-primary rounded-full transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)]"
            style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
        />
    </ProgressPrimitive.Root>
))
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }

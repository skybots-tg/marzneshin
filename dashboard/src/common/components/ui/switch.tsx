import * as React from "react"
import * as SwitchPrimitives from "@radix-ui/react-switch"

import { cn } from "@marzneshin/common/utils"

const Switch = React.forwardRef<
    React.ElementRef<typeof SwitchPrimitives.Root>,
    React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
    <SwitchPrimitives.Root
        className={cn(
            "peer inline-flex h-[26px] w-[44px] shrink-0 cursor-pointer items-center rounded-full border-[0.5px] border-black/[0.04] dark:border-white/[0.06] transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-40 data-[state=checked]:bg-primary data-[state=unchecked]:bg-secondary",
            className
        )}
        {...props}
        ref={ref}
    >
        <SwitchPrimitives.Thumb
            className={cn(
                "pointer-events-none block h-[22px] w-[22px] rounded-full bg-white shadow-apple-sm ring-0 transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)] data-[state=checked]:translate-x-[18px] data-[state=unchecked]:translate-x-[1px]"
            )}
        />
    </SwitchPrimitives.Root>
))
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }

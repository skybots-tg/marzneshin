import * as React from "react"

import { cn } from "@marzneshin/common/utils"

export interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> { }

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, type, ...props }, ref) => {
        return (
            <input
                type={type}
                className={cn(
                    "flex h-10 w-full rounded-lg border-2 border-primary/25 bg-background/70 backdrop-blur-sm px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-0 focus-visible:border-primary/50 focus-visible:shadow-[0_0_10px_rgba(0,200,200,0.15)] dark:focus-visible:shadow-[0_0_15px_rgba(0,255,255,0.3)] disabled:cursor-not-allowed disabled:opacity-50 transition-all duration-300",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Input.displayName = "Input"

export { Input }

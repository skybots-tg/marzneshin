import * as React from "react"

import { cn } from "@marzneshin/common/utils"

export interface TextareaProps
    extends React.TextareaHTMLAttributes<HTMLTextAreaElement> { }

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
    ({ className, ...props }, ref) => {
        return (
            <textarea
                className={cn(
                    "flex min-h-[80px] w-full rounded-[10px] bg-secondary/60 border border-border/40 px-3.5 py-2.5 text-sm placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-0 focus-visible:border-primary/40 disabled:cursor-not-allowed disabled:opacity-40 transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)] resize-none",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Textarea.displayName = "Textarea"

export { Textarea }

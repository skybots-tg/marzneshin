import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@marzneshin/common/utils";

const buttonVariants = cva(
    "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium font-header uppercase tracking-wider ring-offset-background transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 relative overflow-hidden group",
    {
        variants: {
            variant: {
                default:
                    "bg-primary text-primary-foreground hover:bg-primary/90 shadow-[0_0_10px_rgba(0,200,200,0.2)] hover:shadow-[0_0_20px_rgba(0,200,200,0.35)] border-2 border-primary/30 hover:border-primary/50 dark:shadow-[0_0_15px_rgba(0,255,255,0.3)] dark:hover:shadow-[0_0_25px_rgba(0,255,255,0.5)]",
                destructive:
                    "bg-destructive text-destructive-foreground hover:bg-destructive/90 shadow-[0_0_10px_rgba(255,0,100,0.2)] hover:shadow-[0_0_20px_rgba(255,0,100,0.35)] border-2 border-destructive/30 hover:border-destructive/50 dark:shadow-[0_0_15px_rgba(255,0,100,0.3)] dark:hover:shadow-[0_0_25px_rgba(255,0,100,0.5)]",
                "secondary-destructive":
                    "hover:bg-accent text-destructive hover:bg-destructive/20 border-2 border-destructive/30 bg-background/50",
                success:
                    "bg-success text-success-foreground hover:bg-success/80 shadow-[0_0_10px_rgba(0,255,0,0.2)] hover:shadow-[0_0_20px_rgba(0,255,0,0.35)] border-2 border-success/30 hover:border-success/50 dark:shadow-[0_0_15px_rgba(0,255,0,0.3)] dark:hover:shadow-[0_0_25px_rgba(0,255,0,0.5)]",
                outline:
                    "border-2 border-primary/40 bg-background/60 backdrop-blur-sm hover:bg-primary/10 hover:text-primary hover:border-primary/60 hover:shadow-[0_0_10px_rgba(0,200,200,0.2)] dark:hover:shadow-[0_0_15px_rgba(0,255,255,0.3)]",
                secondary:
                    "bg-secondary text-secondary-foreground hover:bg-secondary/80 shadow-[0_0_10px_rgba(255,0,255,0.2)] hover:shadow-[0_0_20px_rgba(255,0,255,0.35)] border-2 border-secondary/30 hover:border-secondary/50 dark:shadow-[0_0_15px_rgba(255,0,255,0.3)] dark:hover:shadow-[0_0_25px_rgba(255,0,255,0.5)]",
                ghost: "hover:bg-accent/20 hover:text-accent-foreground hover:shadow-[0_0_8px_rgba(0,200,200,0.15)] border-2 border-transparent hover:border-primary/30 dark:hover:shadow-[0_0_10px_rgba(0,255,255,0.2)]",
                link: "text-primary underline-offset-4 hover:underline",
            },
            size: {
                default: "h-10 px-4 py-2",
                sm: "h-9 rounded-md px-3",
                lg: "h-11 rounded-md px-8",
                icon: "h-10 w-10",
            },
        },
        defaultVariants: {
            variant: "default",
            size: "default",
        },
    },
);

export interface ButtonProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
    asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant, size, asChild = false, ...props }, ref) => {
        const Comp = asChild ? Slot : "button";
        return (
            <Comp
                className={cn(buttonVariants({ variant, size, className }))}
                ref={ref}
                {...props}
            />
        );
    },
);
Button.displayName = "Button";

export { Button, buttonVariants };

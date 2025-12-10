
import { FC, PropsWithChildren } from "react"
import { Label } from "@marzneshin/common/components"
import { cn } from "@marzneshin/common/utils"
import { useSidebarContext } from "./sidebar-provider";

export interface SidebarGroupProps
    extends PropsWithChildren {
    className: string
}

export const SidebarGroup: FC<SidebarGroupProps> = ({ children, className }) => {
    const { collapsed } = useSidebarContext();

    if (!collapsed)
        return (
            <Label className={cn(className, "text-muted-foreground font-medium text-xs uppercase tracking-wide border-b border-border pb-1 mb-2")}>
                {children}
            </Label>
        )
}

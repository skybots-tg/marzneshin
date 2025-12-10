import { FC, PropsWithChildren, HTMLAttributes } from 'react'
import {
    Card,
    CardContent,
    ScrollArea,
    CardFooter,
    CardHeader,
    CardTitle,
} from '@marzneshin/common/components';
import { cn } from '@marzneshin/common/utils';

interface PageProps {
    title: JSX.Element | string;
    content?: JSX.Element | string;
    footer?: JSX.Element | string;
}

export const Page: FC<PageProps & PropsWithChildren & HTMLAttributes<HTMLDivElement>> = ({
    footer,
    content,
    children,
    title,
    className
}) => {
    return (
        <div className="flex flex-col h-full w-full">
            <div className="mb-4">
                <h1 className="text-2xl font-semibold text-foreground">
                    {title}
                </h1>
            </div>
            <div className={cn("flex flex-col w-full flex-grow", className)}>
                {content || children}
            </div>
            {footer && <div className="mt-4">{footer}</div>}
        </div>
    );
}

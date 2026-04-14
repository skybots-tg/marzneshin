import { FC, PropsWithChildren, HTMLAttributes } from 'react'
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
        <div className="flex flex-col h-full w-full animate-apple-slide-up">
            <div className="mb-5 md:mb-6">
                <h1 className="text-2xl md:text-[28px] font-bold text-foreground tracking-tight leading-tight">
                    {title}
                </h1>
            </div>
            <div className={cn("flex flex-col w-full flex-grow", className)}>
                {content || children}
            </div>
            {footer && <div className="mt-4 md:mt-5">{footer}</div>}
        </div>
    );
}

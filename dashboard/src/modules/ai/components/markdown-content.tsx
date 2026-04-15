import { FC } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import { cn } from '@marzneshin/common/utils'

const sanitizeSchema = {
    ...defaultSchema,
    tagNames: [
        ...(defaultSchema.tagNames ?? []),
        'table',
        'thead',
        'tbody',
        'tr',
        'th',
        'td',
        'del',
        'input',
    ],
    attributes: {
        ...defaultSchema.attributes,
        th: ['align', 'colspan', 'rowspan', 'scope'],
        td: ['align', 'colspan', 'rowspan'],
        table: ['align'],
        input: ['type', 'checked', 'disabled'],
    },
}

interface MarkdownContentProps {
    className?: string
    children: string
}

export const MarkdownContent: FC<MarkdownContentProps> = ({
    className,
    children,
}) => (
    <ReactMarkdown
        className={cn(
            'prose prose-sm max-w-none dark:prose-invert',
            'prose-p:my-2 prose-p:leading-relaxed',
            'prose-headings:my-2 prose-headings:font-semibold',
            'prose-ul:my-2 prose-ol:my-2',
            'prose-li:my-0.5',
            'prose-code:rounded prose-code:bg-background/80 prose-code:px-1 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none',
            'prose-pre:bg-background/80 prose-pre:border prose-pre:border-border prose-pre:rounded-md',
            'prose-table:text-xs prose-th:border prose-td:border prose-th:border-border prose-td:border-border',
            'prose-a:text-primary prose-a:underline-offset-2',
            className,
        )}
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, sanitizeSchema]]}
        components={{
            a: ({ node: _node, ...props }) => (
                <a
                    {...props}
                    target="_blank"
                    rel="noopener noreferrer"
                />
            ),
        }}
    >
        {children}
    </ReactMarkdown>
)

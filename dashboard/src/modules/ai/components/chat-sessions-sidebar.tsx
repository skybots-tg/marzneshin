import { FC, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MessageSquare, Plus, Trash2 } from 'lucide-react'
import { Button } from '@marzneshin/common/components/ui'
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@marzneshin/common/components'
import type { PersistedChatSession } from '../utils/chat-sessions-storage'

interface ChatSessionsSidebarProps {
    sessions: PersistedChatSession[]
    activeId: string
    onSelect: (id: string) => void
    onNew: () => void
    onDelete: (id: string) => void
}

export const ChatSessionsSidebar: FC<ChatSessionsSidebarProps> = ({
    sessions,
    activeId,
    onSelect,
    onNew,
    onDelete,
}) => {
    const { t } = useTranslation()
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

    const ordered = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt)

    return (
        <>
            <div className="flex flex-col w-[220px] shrink-0 border-r border-border/50 pr-3 mr-3 min-h-0">
                <div className="flex items-center justify-between gap-2 pb-3 border-b border-border/50">
                    <span className="text-sm font-medium truncate">{t('ai.chats')}</span>
                    <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="size-8 shrink-0"
                        onClick={onNew}
                        title={t('ai.new-chat')}
                    >
                        <Plus className="size-4" />
                    </Button>
                </div>
                <div className="flex-1 overflow-y-auto py-2 space-y-1 min-h-0">
                    {ordered.map((s) => {
                        const label = s.title.trim() || t('ai.new-chat')
                        const isActive = s.id === activeId
                        return (
                            <div
                                key={s.id}
                                className={`group flex items-center gap-1 rounded-md border border-transparent ${
                                    isActive ? 'bg-muted/80 border-border/60' : 'hover:bg-muted/50'
                                }`}
                            >
                                <button
                                    type="button"
                                    className="flex-1 flex items-center gap-2 min-w-0 text-left text-sm px-2 py-2 rounded-md"
                                    onClick={() => onSelect(s.id)}
                                >
                                    <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
                                    <span className="truncate">{label}</span>
                                </button>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="size-7 shrink-0 opacity-70 group-hover:opacity-100"
                                    title={t('ai.delete-chat')}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setConfirmDeleteId(s.id)
                                    }}
                                >
                                    <Trash2 className="size-3.5" />
                                </Button>
                            </div>
                        )
                    })}
                </div>
            </div>

            <AlertDialog
                open={confirmDeleteId !== null}
                onOpenChange={(open) => !open && setConfirmDeleteId(null)}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>{t('ai.delete-chat')}</AlertDialogTitle>
                        <AlertDialogDescription>{t('ai.delete-chat-confirm')}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={() => {
                                if (confirmDeleteId) onDelete(confirmDeleteId)
                                setConfirmDeleteId(null)
                            }}
                        >
                            {t('delete')}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    )
}

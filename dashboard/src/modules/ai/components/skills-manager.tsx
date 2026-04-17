import { FC, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    Badge,
    Button,
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Label,
    ScrollArea,
    Separator,
    Switch,
    Textarea,
} from '@marzneshin/common/components/ui'
import { BookOpen, Loader2, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
    useAISkillQuery,
    useAISkillsQuery,
    useAISkillCreateMutation,
    useAISkillDeleteMutation,
    useAISkillRevertMutation,
    useAISkillUpdateMutation,
} from '../api'
import type { AISkillSource, AISkillSummary } from '../types'

interface SkillsManagerProps {
    open: boolean
    onClose: () => void
}

interface EditorState {
    name: string
    description: string
    body: string
    enabled: boolean
    isNew: boolean
    dirty: boolean
}

const EMPTY_EDITOR: EditorState = {
    name: '',
    description: '',
    body: '',
    enabled: true,
    isNew: true,
    dirty: false,
}

const SOURCE_BADGE_VARIANT: Record<
    AISkillSource,
    'default' | 'secondary' | 'outline'
> = {
    builtin: 'outline',
    override: 'secondary',
    custom: 'default',
}

const NAME_PATTERN = /^[a-z0-9][a-z0-9\-_]{1,126}$/

const sortSkills = (list: AISkillSummary[]): AISkillSummary[] =>
    [...list].sort((a, b) => a.name.localeCompare(b.name))

export const SkillsManager: FC<SkillsManagerProps> = ({ open, onClose }) => {
    const { t } = useTranslation()
    const { data, isLoading } = useAISkillsQuery()
    const skills = useMemo(() => sortSkills(data ?? []), [data])

    const [selectedName, setSelectedName] = useState<string | null>(null)
    const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR)

    const { data: selectedDetail } = useAISkillQuery(
        editor.isNew ? null : selectedName
    )
    const createMutation = useAISkillCreateMutation()
    const updateMutation = useAISkillUpdateMutation()
    const revertMutation = useAISkillRevertMutation()
    const deleteMutation = useAISkillDeleteMutation()

    useEffect(() => {
        if (!open) return
        if (selectedName === null && skills.length > 0) {
            setSelectedName(skills[0].name)
        }
    }, [open, selectedName, skills])

    useEffect(() => {
        if (!selectedDetail) return
        setEditor({
            name: selectedDetail.name,
            description: selectedDetail.description,
            body: selectedDetail.body,
            enabled: selectedDetail.enabled,
            isNew: false,
            dirty: false,
        })
    }, [selectedDetail])

    const startNewSkill = () => {
        setSelectedName(null)
        setEditor({ ...EMPTY_EDITOR })
    }

    const handleSelect = (name: string) => {
        if (editor.dirty && !window.confirm(t('ai.skills.discard-unsaved'))) {
            return
        }
        setSelectedName(name)
    }

    const selectedSummary = useMemo(
        () => skills.find((s) => s.name === selectedName) ?? null,
        [skills, selectedName]
    )

    const handleSave = async () => {
        const name = editor.name.trim()
        if (!NAME_PATTERN.test(name)) {
            toast.error(t('ai.skills.invalid-name'))
            return
        }
        if (!editor.description.trim()) {
            toast.error(t('ai.skills.description-required'))
            return
        }
        if (!editor.body.trim()) {
            toast.error(t('ai.skills.body-required'))
            return
        }

        try {
            if (editor.isNew) {
                await createMutation.mutateAsync({
                    name,
                    description: editor.description,
                    body: editor.body,
                    enabled: editor.enabled,
                })
                toast.success(t('ai.skills.created'))
                setSelectedName(name)
            } else {
                await updateMutation.mutateAsync({
                    name,
                    body: {
                        description: editor.description,
                        body: editor.body,
                        enabled: editor.enabled,
                    },
                })
                toast.success(t('ai.skills.saved'))
            }
            setEditor((prev) => ({ ...prev, dirty: false, isNew: false }))
        } catch (err) {
            toast.error((err as Error).message ?? t('ai.skills.save-failed'))
        }
    }

    const handleRevert = async () => {
        if (!selectedSummary || selectedSummary.source !== 'override') return
        if (!window.confirm(t('ai.skills.confirm-revert'))) return
        try {
            await revertMutation.mutateAsync(selectedSummary.name)
            toast.success(t('ai.skills.reverted'))
        } catch (err) {
            toast.error((err as Error).message)
        }
    }

    const handleDelete = async () => {
        if (!selectedSummary || selectedSummary.source !== 'custom') return
        if (!window.confirm(t('ai.skills.confirm-delete'))) return
        try {
            await deleteMutation.mutateAsync(selectedSummary.name)
            toast.success(t('ai.skills.deleted'))
            setSelectedName(null)
            setEditor({ ...EMPTY_EDITOR })
        } catch (err) {
            toast.error((err as Error).message)
        }
    }

    const isBusy =
        createMutation.isPending ||
        updateMutation.isPending ||
        revertMutation.isPending ||
        deleteMutation.isPending

    return (
        <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
            <DialogContent className="max-w-5xl w-full h-[80vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <BookOpen className="h-5 w-5" /> {t('ai.skills.title')}
                    </DialogTitle>
                    <DialogDescription>
                        {t('ai.skills.description')}
                    </DialogDescription>
                </DialogHeader>

                <div className="flex flex-1 gap-4 min-h-0">
                    <div className="w-[280px] flex flex-col border rounded-md">
                        <div className="p-2 border-b flex items-center justify-between">
                            <span className="text-xs font-medium text-muted-foreground">
                                {skills.length} {t('ai.skills.count-suffix')}
                            </span>
                            <Button
                                size="sm"
                                variant="ghost"
                                onClick={startNewSkill}
                                className="h-7 px-2"
                            >
                                <Plus className="h-3.5 w-3.5 mr-1" />
                                {t('ai.skills.new')}
                            </Button>
                        </div>
                        <ScrollArea className="flex-1">
                            {isLoading ? (
                                <div className="flex items-center justify-center p-6">
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                </div>
                            ) : (
                                <ul className="py-1">
                                    {skills.map((s) => (
                                        <li key={s.name}>
                                            <button
                                                onClick={() => handleSelect(s.name)}
                                                className={
                                                    'w-full text-left px-3 py-2 text-xs hover:bg-muted transition-colors ' +
                                                    (selectedName === s.name && !editor.isNew
                                                        ? 'bg-muted'
                                                        : '')
                                                }
                                            >
                                                <div className="flex items-center justify-between gap-2">
                                                    <span
                                                        className={
                                                            'font-mono truncate ' +
                                                            (!s.enabled
                                                                ? 'line-through text-muted-foreground'
                                                                : '')
                                                        }
                                                    >
                                                        {s.name}
                                                    </span>
                                                    <Badge
                                                        variant={SOURCE_BADGE_VARIANT[s.source]}
                                                        className="text-[10px] h-4 px-1.5"
                                                    >
                                                        {t(`ai.skills.source-${s.source}`)}
                                                    </Badge>
                                                </div>
                                                <p className="text-[10px] text-muted-foreground line-clamp-2 mt-0.5">
                                                    {s.description}
                                                </p>
                                            </button>
                                        </li>
                                    ))}
                                    {editor.isNew && (
                                        <li>
                                            <div className="w-full px-3 py-2 text-xs bg-muted/50 border-l-2 border-primary">
                                                <span className="font-mono italic">
                                                    {editor.name || t('ai.skills.new-placeholder')}
                                                </span>
                                                <Badge
                                                    variant="default"
                                                    className="ml-2 text-[10px] h-4 px-1.5"
                                                >
                                                    {t('ai.skills.unsaved')}
                                                </Badge>
                                            </div>
                                        </li>
                                    )}
                                </ul>
                            )}
                        </ScrollArea>
                    </div>

                    <Separator orientation="vertical" />

                    <div className="flex-1 flex flex-col min-w-0">
                        <SkillEditor
                            editor={editor}
                            setEditor={setEditor}
                            source={selectedSummary?.source ?? null}
                            isNew={editor.isNew}
                        />
                    </div>
                </div>

                <DialogFooter className="flex items-center justify-between sm:justify-between gap-2 pt-2 border-t">
                    <div className="flex gap-2">
                        {!editor.isNew && selectedSummary?.source === 'override' && (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={handleRevert}
                                disabled={isBusy}
                            >
                                <RotateCcw className="h-3.5 w-3.5 mr-1" />
                                {t('ai.skills.revert')}
                            </Button>
                        )}
                        {!editor.isNew && selectedSummary?.source === 'custom' && (
                            <Button
                                variant="destructive"
                                size="sm"
                                onClick={handleDelete}
                                disabled={isBusy}
                            >
                                <Trash2 className="h-3.5 w-3.5 mr-1" />
                                {t('ai.skills.delete')}
                            </Button>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={onClose}>
                            {t('ai.skills.close')}
                        </Button>
                        <Button
                            size="sm"
                            onClick={handleSave}
                            disabled={isBusy || !editor.dirty}
                        >
                            {isBusy ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                            ) : (
                                <Save className="h-3.5 w-3.5 mr-1" />
                            )}
                            {editor.isNew
                                ? t('ai.skills.create')
                                : t('ai.skills.save')}
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

interface SkillEditorProps {
    editor: EditorState
    setEditor: (updater: (prev: EditorState) => EditorState) => void
    source: AISkillSource | null
    isNew: boolean
}

const SkillEditor: FC<SkillEditorProps> = ({
    editor,
    setEditor,
    source,
    isNew,
}) => {
    const { t } = useTranslation()
    const patch = (updates: Partial<EditorState>) =>
        setEditor((prev) => ({ ...prev, ...updates, dirty: true }))

    return (
        <div className="flex flex-col gap-3 h-full min-h-0">
            <div className="grid grid-cols-2 gap-3">
                <div>
                    <Label className="text-xs">{t('ai.skills.name')}</Label>
                    <Input
                        value={editor.name}
                        onChange={(e) => patch({ name: e.target.value })}
                        placeholder="deploy-new-node"
                        disabled={!isNew}
                        className="mt-1 font-mono text-xs"
                    />
                    {!isNew && source && (
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                            {t(`ai.skills.source-hint-${source}`)}
                        </p>
                    )}
                </div>
                <div className="flex items-end gap-3">
                    <div className="flex items-center gap-2">
                        <Switch
                            checked={editor.enabled}
                            onCheckedChange={(v) => patch({ enabled: v })}
                        />
                        <Label className="text-xs">
                            {t('ai.skills.enabled')}
                        </Label>
                    </div>
                </div>
            </div>

            <div>
                <Label className="text-xs">
                    {t('ai.skills.description')}
                </Label>
                <Textarea
                    value={editor.description}
                    onChange={(e) => patch({ description: e.target.value })}
                    placeholder={t('ai.skills.description-placeholder')}
                    className="mt-1 min-h-[70px] text-xs"
                />
                <p className="text-[10px] text-muted-foreground mt-0.5">
                    {t('ai.skills.description-hint')}
                </p>
            </div>

            <div className="flex-1 flex flex-col min-h-0">
                <Label className="text-xs">{t('ai.skills.body')}</Label>
                <Textarea
                    value={editor.body}
                    onChange={(e) => patch({ body: e.target.value })}
                    placeholder={t('ai.skills.body-placeholder')}
                    className="mt-1 flex-1 font-mono text-xs resize-none"
                />
                <p className="text-[10px] text-muted-foreground mt-0.5">
                    {t('ai.skills.body-hint')}
                </p>
            </div>
        </div>
    )
}

import { FC, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Input, Label, Textarea } from '@marzneshin/common/components/ui'
import { useAISettingsQuery, useAISettingsUpdateMutation } from '../api'
import type { AISettings } from '../types'

interface AISettingsWidgetProps {
    open: boolean
    onClose: () => void
}

export const AISettingsWidget: FC<AISettingsWidgetProps> = ({ open, onClose }) => {
    const { t } = useTranslation()
    const { data: settings } = useAISettingsQuery()
    const mutation = useAISettingsUpdateMutation()

    const [form, setForm] = useState<AISettings>({
        api_key: '',
        default_model: 'gpt-4o',
        thinking_model: 'o3',
        max_tokens: 16384,
        temperature: 0.7,
        system_prompt: '',
    })

    useEffect(() => {
        if (settings) {
            setForm((prev) => ({
                ...prev,
                default_model: settings.default_model,
                thinking_model: settings.thinking_model,
                max_tokens: settings.max_tokens,
                temperature: settings.temperature,
                system_prompt: settings.system_prompt,
            }))
        }
    }, [settings])

    const handleSave = () => {
        mutation.mutate(form, {
            onSuccess: () => onClose(),
        })
    }

    if (!open) return null

    return (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-background border border-border rounded-xl shadow-lg w-full max-w-md p-6 space-y-4">
                <h3 className="text-lg font-semibold">{t('ai.settings')}</h3>

                <div className="space-y-3">
                    <div>
                        <Label className="text-xs">{t('ai.api-key')}</Label>
                        <Input
                            type="password"
                            placeholder={t('ai.api-key-placeholder')}
                            value={form.api_key}
                            onChange={(e) =>
                                setForm({ ...form, api_key: e.target.value })
                            }
                            className="mt-1"
                        />
                        {settings?.configured && !form.api_key && (
                            <p className="text-xs text-green-600 mt-1">
                                {t('ai.configured')}
                            </p>
                        )}
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <Label className="text-xs">{t('ai.default-model')}</Label>
                            <Input
                                value={form.default_model}
                                onChange={(e) =>
                                    setForm({ ...form, default_model: e.target.value })
                                }
                                className="mt-1"
                            />
                        </div>
                        <div>
                            <Label className="text-xs">{t('ai.thinking-model')}</Label>
                            <Input
                                value={form.thinking_model}
                                onChange={(e) =>
                                    setForm({ ...form, thinking_model: e.target.value })
                                }
                                className="mt-1"
                            />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <Label className="text-xs">{t('ai.max-tokens')}</Label>
                            <Input
                                type="number"
                                value={form.max_tokens}
                                onChange={(e) =>
                                    setForm({
                                        ...form,
                                        max_tokens: parseInt(e.target.value) || 16384,
                                    })
                                }
                                className="mt-1"
                            />
                        </div>
                        <div>
                            <Label className="text-xs">{t('ai.temperature')}</Label>
                            <Input
                                type="number"
                                step="0.1"
                                min="0"
                                max="2"
                                value={form.temperature}
                                onChange={(e) =>
                                    setForm({
                                        ...form,
                                        temperature: parseFloat(e.target.value) || 0.7,
                                    })
                                }
                                className="mt-1"
                            />
                        </div>
                    </div>

                    <div>
                        <Label className="text-xs">{t('ai.system-prompt')}</Label>
                        <Textarea
                            placeholder={t('ai.system-prompt-placeholder')}
                            value={form.system_prompt}
                            onChange={(e) =>
                                setForm({ ...form, system_prompt: e.target.value })
                            }
                            className="mt-1 min-h-[80px]"
                        />
                    </div>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button onClick={handleSave} disabled={mutation.isPending}>
                        {t('ai.save-settings')}
                    </Button>
                </div>
            </div>
        </div>
    )
}

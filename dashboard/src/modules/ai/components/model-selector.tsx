import { FC } from 'react'
import { useTranslation } from 'react-i18next'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@marzneshin/common/components/ui'
import { useAIModelsQuery } from '../api'

interface ModelSelectorProps {
    value: string
    onChange: (model: string) => void
    configured: boolean
}

export const ModelSelector: FC<ModelSelectorProps> = ({
    value,
    onChange,
    configured,
}) => {
    const { t } = useTranslation()
    const { data, isLoading } = useAIModelsQuery(configured)

    const models = data?.models || []

    return (
        <Select value={value} onValueChange={onChange} disabled={!configured}>
            <SelectTrigger className="w-[220px] h-8 text-xs">
                <SelectValue
                    placeholder={
                        isLoading
                            ? t('ai.loading-models')
                            : t('ai.select-model')
                    }
                />
            </SelectTrigger>
            <SelectContent>
                {models.map((m) => (
                    <SelectItem key={m.id} value={m.id} className="text-xs">
                        {m.id}
                    </SelectItem>
                ))}
                {!isLoading && models.length === 0 && (
                    <SelectItem value="_none" disabled className="text-xs">
                        {t('ai.select-model')}
                    </SelectItem>
                )}
            </SelectContent>
        </Select>
    )
}

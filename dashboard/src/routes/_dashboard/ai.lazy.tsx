import { Page } from '@marzneshin/common/components'
import { ChatWorkspace, AISettingsWidget } from '@marzneshin/modules/ai'
import { createLazyFileRoute } from '@tanstack/react-router'
import { useState, type FC } from 'react'
import { useTranslation } from 'react-i18next'
import { SudoRoute } from '@marzneshin/libs/sudo-routes'

const AIAssistantPage: FC = () => {
    const { t } = useTranslation()
    const [settingsOpen, setSettingsOpen] = useState(false)

    return (
        <Page title={t('ai.title')} className="h-[calc(100vh-10rem)]">
            <ChatWorkspace onOpenSettings={() => setSettingsOpen(true)} />
            <AISettingsWidget
                open={settingsOpen}
                onClose={() => setSettingsOpen(false)}
            />
        </Page>
    )
}

export const Route = createLazyFileRoute('/_dashboard/ai')({
    component: () => (
        <SudoRoute>
            <AIAssistantPage />
        </SudoRoute>
    ),
})

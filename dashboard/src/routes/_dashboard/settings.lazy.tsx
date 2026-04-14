import { Page, VStack } from '@marzneshin/common/components'
import { CertificateWidget, SSHPinWidget } from '@marzneshin/modules/settings'
import { SubscriptionSettingsWidget } from '@marzneshin/modules/settings/subscription'
import { DatabaseSettingsWidget } from '@marzneshin/modules/settings/database'
import { createLazyFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { SudoRoute } from '@marzneshin/libs/sudo-routes'

export const Settings = () => {
  const { t } = useTranslation()
  return (
    <Page
      title={t('settings')}
      className="sm:flex flex-col lg:grid grid-cols-2 gap-3 h-full"
    >
      <VStack className="gap-3">
        <SubscriptionSettingsWidget />
        <CertificateWidget />
      </VStack>
      <VStack className="gap-3">
        <DatabaseSettingsWidget />
        <SSHPinWidget />
      </VStack>
    </Page>
  )
}

export const Route = createLazyFileRoute('/_dashboard/settings')({
  component: () => (
    <SudoRoute>
      {' '}
      <Settings />{' '}
    </SudoRoute>
  ),
})

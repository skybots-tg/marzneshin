import { lazy, Suspense } from 'react'
import { Page, VStack, Card } from '@marzneshin/common/components'
import { CertificateWidget, SSHPinWidget } from '@marzneshin/modules/settings'
import { DatabaseSettingsWidget } from '@marzneshin/modules/settings/database'
import { NotificationEventsWidget } from '@marzneshin/modules/settings/notifications'
import { createLazyFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { SudoRoute } from '@marzneshin/libs/sudo-routes'

const SubscriptionSettingsWidget = lazy(() =>
  import('@marzneshin/modules/settings/subscription').then((m) => ({
    default: m.SubscriptionSettingsWidget,
  })),
)

const WidgetSkeleton = () => (
  <Card className="h-64 animate-pulse bg-secondary/30" />
)

export const Settings = () => {
  const { t } = useTranslation()
  return (
    <Page
      title={t('settings')}
      className="sm:flex flex-col lg:grid grid-cols-2 gap-3 h-full"
    >
      <VStack className="gap-3">
        <Suspense fallback={<WidgetSkeleton />}>
          <SubscriptionSettingsWidget />
        </Suspense>
        <NotificationEventsWidget />
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

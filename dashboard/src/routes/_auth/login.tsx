import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@marzneshin/common/components';
import { LoginForm, useAuth } from '@marzneshin/modules/auth';
import { createFileRoute } from '@tanstack/react-router'
import { FC } from 'react'
import { useTranslation } from 'react-i18next';
import { ShieldCheck } from 'lucide-react';

const LoginPage: FC = () => {
  const { t } = useTranslation();
  const { removeAuthToken } = useAuth()
  removeAuthToken()
  return (
    <div className='flex flex-col justify-center items-center p-6 w-full max-w-md mx-auto animate-apple-fade-in'>
      <div className="flex flex-col items-center mb-8">
        <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
          <ShieldCheck className="size-7 text-primary" />
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Marzneshin</h1>
      </div>
      <Card className="w-full shadow-apple-lg">
        <CardHeader className="pb-2">
          <CardTitle className="text-xl">
            {t('login')}
          </CardTitle>
          <CardDescription>
            {t('login-description')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <LoginForm />
        </CardContent>
      </Card>
    </div>
  );
};

export const Route = createFileRoute('/_auth/login')({
  component: () => <LoginPage />
})

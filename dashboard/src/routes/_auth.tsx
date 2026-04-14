import { Outlet, createFileRoute } from '@tanstack/react-router'
import network from '@marzneshin/assets/undraw_connected_world_wuay.svg'

const AuthLayout = () => {
  return (
    <div className='grid-cols-2 w-screen h-screen md:grid bg-background'>
      <div className="w-full h-full flex items-center justify-center">
        <Outlet />
      </div>
      <div className='hidden justify-center items-center w-full h-full md:flex bg-gradient-to-br from-primary/5 via-primary/10 to-primary/5 dark:from-primary/8 dark:via-primary/15 dark:to-primary/5'>
        <img src={network} className="w-2/5 h-2/5 opacity-80" />
      </div>
    </div>
  )
}

export const Route = createFileRoute('/_auth')({
  component: () => <AuthLayout />,
})

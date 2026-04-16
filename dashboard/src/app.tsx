import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider, createHashHistory, createRouter } from '@tanstack/react-router'
import '@marzneshin/features/i18n'
import './globals.css'

import { routeTree } from './routeTree.gen'

// Recover from stale chunks after a new deploy: when a dynamic import
// points to a hashed file that no longer exists on the server, reload
// the page once to pick up the fresh index.html with new chunk names.
// A sessionStorage flag prevents reload loops if the failure is caused
// by a real infrastructure problem rather than a stale tab.
const RELOAD_FLAG = 'marzneshin:chunk-reloaded'

const isChunkLoadError = (reason: unknown): boolean => {
    const message =
        typeof reason === 'string'
            ? reason
            : reason instanceof Error
                ? reason.message
                : ''
    return (
        /Failed to fetch dynamically imported module/i.test(message) ||
        /error loading dynamically imported module/i.test(message) ||
        /Importing a module script failed/i.test(message)
    )
}

const reloadOnce = () => {
    if (sessionStorage.getItem(RELOAD_FLAG)) return
    sessionStorage.setItem(RELOAD_FLAG, '1')
    window.location.reload()
}

window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault()
    reloadOnce()
})

window.addEventListener('unhandledrejection', (event) => {
    if (isChunkLoadError(event.reason)) {
        event.preventDefault()
        reloadOnce()
    }
})

window.addEventListener('load', () => {
    sessionStorage.removeItem(RELOAD_FLAG)
})

const hashHistory = createHashHistory()

const router = createRouter({ routeTree, history: hashHistory })

declare module '@tanstack/react-router' {
    interface Register {
        router: typeof router
    }
}

const rootElement = document.getElementById('app')!
if (!rootElement.innerHTML) {
    const root = ReactDOM.createRoot(rootElement)
    root.render(
        <StrictMode>
            <RouterProvider router={router} />
        </StrictMode>,
    )
}

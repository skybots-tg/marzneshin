import { Outlet, createFileRoute } from '@tanstack/react-router'
import { Globe, Server, ShieldCheck, Zap } from 'lucide-react'

/**
 * Правая половина экрана входа.
 *
 * Здесь лежала растровая по духу undraw-иллюстрация на 142 КБ — единственный
 * ассет проекта, использованный ровно один раз. В тёмной теме она была
 * светлым пятном во весь экран, и вылечить это можно было только фильтрами.
 * Рисунок собран из тех же иконок, что и весь остальной интерфейс: он берёт
 * цвета из токенов темы и весит столько же, сколько четыре иконки.
 */
const AuthArtwork = () => (
    <div className="relative flex items-center justify-center w-full h-full">
        {/* Мягкое свечение: единственное цветное пятно на экране, и оно за
            иллюстрацией, а не в ней — так оно одинаково работает в обеих темах. */}
        <div
            aria-hidden="true"
            className="absolute size-[28rem] rounded-full bg-primary/10 blur-3xl"
        />
        <Globe
            aria-hidden="true"
            className="relative size-64 text-primary/30"
            strokeWidth={0.6}
        />
        <div
            aria-hidden="true"
            className="absolute size-[22rem] rounded-full border border-primary/15"
        />
        <div
            aria-hidden="true"
            className="absolute size-[30rem] rounded-full border border-primary/[0.07]"
        />
        <Server
            aria-hidden="true"
            className="absolute size-6 text-primary/50 -translate-x-40 -translate-y-24"
            strokeWidth={1.25}
        />
        <ShieldCheck
            aria-hidden="true"
            className="absolute size-6 text-primary/50 translate-x-40 -translate-y-12"
            strokeWidth={1.25}
        />
        <Zap
            aria-hidden="true"
            className="absolute size-6 text-primary/50 translate-x-28 translate-y-36"
            strokeWidth={1.25}
        />
    </div>
)

const AuthLayout = () => {
    return (
        <div className="grid-cols-2 w-screen h-screen md:grid bg-background">
            <div className="w-full h-full flex items-center justify-center">
                <Outlet />
            </div>
            <div className="hidden overflow-hidden justify-center items-center w-full h-full md:flex bg-gradient-to-br from-primary/[0.04] via-transparent to-primary/[0.06]">
                <AuthArtwork />
            </div>
        </div>
    )
}

export const Route = createFileRoute('/_auth')({
    component: () => <AuthLayout />,
})

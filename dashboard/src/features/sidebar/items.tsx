import { SidebarObject } from '@marzneshin/common/components';
import {
    Home,
    Users,
    Server,
    Box,
    Network,
    ShieldCheck,
    Settings,
} from 'lucide-react';

const iconClass = "size-[18px]";

export const sidebarItems: SidebarObject = {
    dashboard: [
        {
            title: 'home',
            to: '/',
            icon: <Home className={iconClass} />,
            isParent: false,
        },
    ],
    management: [
        {
            title: 'users',
            to: '/users',
            icon: <Users className={iconClass} />,
            isParent: false,
        },
        {
            title: 'services',
            to: '/services',
            icon: <Server className={iconClass} />,
            isParent: false,
        },
        {
            title: 'nodes',
            to: '/nodes',
            icon: <Box className={iconClass} />,
            isParent: false,
        },
        {
            title: 'hosts',
            to: '/hosts',
            icon: <Network className={iconClass} />,
            isParent: false,
        },
    ],
    system: [
        {
            title: 'admins',
            to: '/admins',
            icon: <ShieldCheck className={iconClass} />,
            isParent: false,
        },
        {
            title: 'settings',
            to: '/settings',
            icon: <Settings className={iconClass} />,
            isParent: false,
        },
    ]
};

export const sidebarItemsNonSudoAdmin: SidebarObject = {
    dashboard: [
        {
            title: 'home',
            to: '/',
            icon: <Home className={iconClass} />,
            isParent: false,
        },
    ],
    management: [
        {
            title: 'users',
            to: '/users',
            icon: <Users className={iconClass} />,
            isParent: false,
        },
    ],
};

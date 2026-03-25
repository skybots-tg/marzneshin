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
import i18n from "@marzneshin/features/i18n";

const iconClass = "size-[18px]";

export const sidebarItems: SidebarObject = {
    Dashboard: [
        {
            title: i18n.t('home'),
            to: '/',
            icon: <Home className={iconClass} />,
            isParent: false,
        },
    ],
    Management: [
        {
            title: i18n.t('users'),
            to: '/users',
            icon: <Users className={iconClass} />,
            isParent: false,
        },
        {
            title: i18n.t('services'),
            to: '/services',
            icon: <Server className={iconClass} />,
            isParent: false,
        },
        {
            title: i18n.t('nodes'),
            to: '/nodes',
            icon: <Box className={iconClass} />,
            isParent: false,
        },
        {
            title: i18n.t('hosts'),
            to: '/hosts',
            icon: <Network className={iconClass} />,
            isParent: false,
        },
    ],
    System: [
        {
            title: i18n.t('admins'),
            to: '/admins',
            icon: <ShieldCheck className={iconClass} />,
            isParent: false,
        },
        {
            title: i18n.t('settings'),
            to: '/settings',
            icon: <Settings className={iconClass} />,
            isParent: false,
        },
    ]
};

export const sidebarItemsNonSudoAdmin: SidebarObject = {
    Dashboard: [
        {
            title: i18n.t('home'),
            to: '/',
            icon: <Home className={iconClass} />,
            isParent: false,
        },
    ],
    Management: [
        {
            title: i18n.t('users'),
            to: '/users',
            icon: <Users className={iconClass} />,
            isParent: false,
        },
    ],
};

import { SidebarObject } from '@marzneshin/common/components';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { 
    faHouse, 
    faUsers, 
    faServer, 
    faCubes, 
    faNetworkWired, 
    faUserShield, 
    faGear 
} from '@fortawesome/free-solid-svg-icons';

export const sidebarItems: SidebarObject = {
    Dashboard: [
        {
            title: 'Home',
            to: '/',
            icon: <FontAwesomeIcon icon={faHouse} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
    ],
    Management: [
        {
            title: 'Users',
            to: '/users',
            icon: <FontAwesomeIcon icon={faUsers} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
        {
            title: 'Services',
            to: '/services',
            icon: <FontAwesomeIcon icon={faServer} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
        {
            title: 'Nodes',
            to: '/nodes',
            icon: <FontAwesomeIcon icon={faCubes} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
        {
            title: 'Hosts',
            to: '/hosts',
            icon: <FontAwesomeIcon icon={faNetworkWired} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
    ],
    System: [
        {
            title: 'Admins',
            to: '/admins',
            icon: <FontAwesomeIcon icon={faUserShield} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
        {
            title: 'Settings',
            to: '/settings',
            icon: <FontAwesomeIcon icon={faGear} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
    ]
};

export const sidebarItemsNonSudoAdmin: SidebarObject = {
    Dashboard: [
        {
            title: 'Home',
            to: '/',
            icon: <FontAwesomeIcon icon={faHouse} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
    ],
    Management: [
        {
            title: 'Users',
            to: '/users',
            icon: <FontAwesomeIcon icon={faUsers} className="w-5 h-5 text-foreground" />,
            isParent: false,
        },
    ],
};

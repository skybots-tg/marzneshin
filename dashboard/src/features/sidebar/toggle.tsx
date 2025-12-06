
import { Button } from '@marzneshin/common/components';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBars, faXmark } from '@fortawesome/free-solid-svg-icons';
import { FC } from 'react';

interface ToggleButtonProps {
    collapsed: boolean;
    onToggle: () => void;
}

export const ToggleButton: FC<ToggleButtonProps> = ({ collapsed, onToggle }) => {
    const icon = collapsed ? faBars : faXmark;

    return (
        <Button 
            className="p-2 bg-background/40 backdrop-blur-md border-2 border-primary/30 text-primary hover:bg-primary/15 hover:border-primary/50 shadow-[0_0_8px_rgba(0,200,200,0.15)] hover:shadow-[0_0_15px_rgba(0,200,200,0.25)] dark:shadow-[0_0_10px_rgba(0,255,255,0.2)] dark:hover:shadow-[0_0_20px_rgba(0,255,255,0.4)]" 
            onClick={onToggle}
            variant="outline"
        >
            <FontAwesomeIcon icon={icon} className="w-4 h-4" />
        </Button>
    );
};

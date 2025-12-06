
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
            className="p-2 bg-background/30 backdrop-blur-sm border-2 border-primary/50 text-primary hover:bg-primary/20 hover:border-primary shadow-[0_0_10px_rgba(0,255,255,0.2)] hover:shadow-[0_0_20px_rgba(0,255,255,0.4)]" 
            onClick={onToggle}
            variant="outline"
        >
            <FontAwesomeIcon icon={icon} className="w-4 h-4" />
        </Button>
    );
};

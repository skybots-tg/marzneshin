
import { Button } from '@marzneshin/common/components';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronRight, faChevronLeft } from '@fortawesome/free-solid-svg-icons';
import { FC } from 'react';

interface ToggleButtonProps {
    collapsed: boolean;
    onToggle: () => void;
}

export const ToggleButton: FC<ToggleButtonProps> = ({ collapsed, onToggle }) => {
    const icon = collapsed ? faChevronRight : faChevronLeft;

    return (
        <Button 
            className="p-2 bg-background/60 backdrop-blur-xl border border-border hover:bg-accent/50 hover:border-border shadow-md hover:shadow-lg" 
            onClick={onToggle}
            variant="outline"
            size="icon"
        >
            <FontAwesomeIcon icon={icon} className="w-4 h-4 text-foreground" />
        </Button>
    );
};

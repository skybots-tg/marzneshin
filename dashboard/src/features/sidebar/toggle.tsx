import { Button } from '@marzneshin/common/components';
import { ChevronRight, ChevronLeft } from 'lucide-react';
import { FC } from 'react';

interface ToggleButtonProps {
    collapsed: boolean;
    onToggle: () => void;
}

export const ToggleButton: FC<ToggleButtonProps> = ({ collapsed, onToggle }) => {
    return (
        <Button
            className="h-8 w-8 rounded-lg hover:bg-secondary transition-colors"
            onClick={onToggle}
            variant="ghost"
            size="icon"
        >
            {collapsed
                ? <ChevronRight className="size-4 text-muted-foreground" />
                : <ChevronLeft className="size-4 text-muted-foreground" />
            }
        </Button>
    );
};

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
            className="h-7 w-7 rounded-full hover:bg-secondary/60"
            onClick={onToggle}
            variant="ghost"
            size="icon"
        >
            {collapsed
                ? <ChevronRight className="size-3.5 text-muted-foreground" />
                : <ChevronLeft className="size-3.5 text-muted-foreground" />
            }
        </Button>
    );
};

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSpinner } from '@fortawesome/free-solid-svg-icons';

export const Loading = () => (
    <div className="fixed inset-0 bg-black/90 backdrop-blur-sm flex items-center justify-center z-50">
        <div className="flex flex-col items-center gap-4">
            <FontAwesomeIcon 
                icon={faSpinner} 
                className="animate-spin text-primary size-12 drop-shadow-[0_0_15px_rgba(0,255,255,0.5)]" 
            />
            <div className="text-primary font-header uppercase tracking-widest text-lg animate-pulse">
                Loading...
            </div>
            <div className="h-1 w-48 bg-background/30 rounded-full overflow-hidden">
                <div className="h-full w-full bg-gradient-to-r from-primary via-secondary to-primary animate-cyber-scan"></div>
            </div>
        </div>
    </div>
);

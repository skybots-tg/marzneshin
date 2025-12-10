import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSpinner } from '@fortawesome/free-solid-svg-icons';

export const Loading = () => (
    <div className="frosted-overlay fixed inset-0 flex items-center justify-center z-50">
        <div className="glass-panel flex flex-col items-center gap-4">
            <FontAwesomeIcon 
                icon={faSpinner} 
                className="animate-spin text-primary size-12" 
            />
            <div className="text-foreground font-medium text-lg">
                Loading...
            </div>
        </div>
    </div>
);

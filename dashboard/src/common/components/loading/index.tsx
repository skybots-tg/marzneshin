import { Loader2 } from 'lucide-react';

export const Loading = () => (
    <div className="frosted-overlay fixed inset-0 flex items-center justify-center z-50">
        <div className="glass-panel flex flex-col items-center gap-3">
            <Loader2 className="animate-spin text-primary size-10" />
            <div className="text-foreground font-medium text-base">
                Loading...
            </div>
        </div>
    </div>
);

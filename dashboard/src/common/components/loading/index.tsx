import { Loader2 } from 'lucide-react';

export const Loading = ({ inline = false }: { inline?: boolean }) => {
    if (inline) {
        return (
            <div className="flex flex-1 items-center justify-center py-16">
                <Loader2 className="animate-spin text-primary size-8" />
            </div>
        );
    }

    return (
        <div className="frosted-overlay fixed inset-0 flex items-center justify-center z-50">
            <div className="glass-panel flex flex-col items-center gap-3">
                <Loader2 className="animate-spin text-primary size-10" />
            </div>
        </div>
    );
};

import React from 'react';
import { Loader2 } from 'lucide-react';

export interface LoadingStateProps {
  message?: string;
  description?: string;
  className?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = 'Loading telemetry & incident state...',
  description = 'Querying backend REST services',
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center p-12 text-center bg-noc-surface border border-noc-border rounded-lg ${className}`}
      role="status"
    >
      <Loader2 className="w-8 h-8 text-blue-500 animate-spin mb-4" />
      <h3 className="text-sm font-medium text-noc-text-primary tracking-wide">{message}</h3>
      {description && <p className="text-xs text-noc-text-muted mt-1">{description}</p>}
    </div>
  );
};

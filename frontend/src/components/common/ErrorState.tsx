import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export interface ErrorStateProps {
  title?: string;
  message: string;
  details?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Service Query Error',
  message,
  details,
  onRetry,
  className = '',
}) => {
  return (
    <div
      className={`bg-rose-950/30 border border-rose-800/60 rounded-lg p-6 flex flex-col items-start gap-4 ${className}`}
      role="alert"
    >
      <div className="flex items-start gap-3 w-full">
        <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-semibold text-rose-200">{title}</h4>
          <p className="text-xs text-rose-300 mt-1 leading-relaxed">{message}</p>
          {details && (
            <pre className="mt-2 p-2 bg-black/40 border border-rose-900/50 rounded text-xs font-mono text-rose-400 overflow-x-auto max-w-full">
              {details}
            </pre>
          )}
        </div>
      </div>

      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-900/40 hover:bg-rose-800/60 text-rose-200 border border-rose-700/60 rounded text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-rose-500"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Retry Operation</span>
        </button>
      )}
    </div>
  );
};

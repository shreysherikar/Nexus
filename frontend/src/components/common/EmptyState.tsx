import React from 'react';
import { LucideIcon, Inbox } from 'lucide-react';

export interface EmptyStateProps {
  title: string;
  description: string;
  icon?: LucideIcon;
  action?: {
    label: string;
    onClick: () => void;
  };
  note?: string;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon: Icon = Inbox,
  action,
  note,
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center p-12 text-center bg-noc-surface border border-noc-border rounded-lg ${className}`}
    >
      <div className="w-12 h-12 rounded-full bg-noc-base border border-noc-border flex items-center justify-center mb-4 text-noc-text-muted">
        <Icon className="w-6 h-6" />
      </div>
      <h3 className="text-sm font-semibold text-noc-text-primary tracking-wide">{title}</h3>
      <p className="text-xs text-noc-text-secondary max-w-md mt-1.5 leading-relaxed">
        {description}
      </p>

      {note && (
        <div className="mt-3 px-3 py-1 bg-noc-base border border-noc-border/80 rounded text-xs font-mono text-noc-text-muted">
          {note}
        </div>
      )}

      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-5 px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400"
        >
          {action.label}
        </button>
      )}
    </div>
  );
};

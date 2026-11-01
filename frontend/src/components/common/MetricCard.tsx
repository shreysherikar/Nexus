import React from 'react';
import { LucideIcon } from 'lucide-react';

export interface MetricCardProps {
  title: string;
  value: string | number;
  unit?: string;
  subtitle?: string;
  delta?: {
    value: string | number;
    isPositive?: boolean;
    label?: string;
  };
  status?: 'healthy' | 'warning' | 'critical' | 'neutral' | 'unknown';
  icon?: LucideIcon;
  loading?: boolean;
  className?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit,
  subtitle,
  delta,
  status = 'neutral',
  icon: Icon,
  loading = false,
  className = '',
}) => {
  const statusBorder = {
    healthy: 'border-l-emerald-500',
    warning: 'border-l-amber-500',
    critical: 'border-l-rose-500',
    neutral: 'border-l-slate-600',
    unknown: 'border-l-slate-500',
  }[status] || 'border-l-slate-600';

  return (
    <div
      className={`bg-noc-surface border border-noc-border border-l-4 ${statusBorder} rounded-lg p-4 shadow-sm flex flex-col justify-between transition-colors hover:border-noc-borderHighlight ${className}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-noc-text-secondary uppercase tracking-wider">
          {title}
        </span>
        {Icon && <Icon className="w-4 h-4 text-noc-text-muted shrink-0" />}
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        {loading ? (
          <div className="h-8 w-24 bg-slate-800 animate-pulse rounded" />
        ) : (
          <>
            <span className="text-2xl font-mono font-bold text-noc-text-primary tracking-tight">
              {value}
            </span>
            {unit && <span className="text-xs font-mono text-noc-text-muted">{unit}</span>}
          </>
        )}
      </div>

      {(subtitle || delta) && (
        <div className="mt-2 pt-2 border-t border-noc-border/60 flex items-center justify-between text-xs text-noc-text-muted">
          {subtitle && <span className="truncate">{subtitle}</span>}
          {delta && (
            <span
              className={`font-mono font-medium ${
                delta.isPositive ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {delta.isPositive ? '▲' : '▼'} {delta.value} {delta.label || ''}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

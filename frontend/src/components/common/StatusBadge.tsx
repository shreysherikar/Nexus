import React from 'react';

export type OperationalStatus = 'healthy' | 'warning' | 'degraded' | 'critical' | 'unknown' | 'offline';

export interface StatusBadgeProps {
  status: OperationalStatus;
  label?: string;
  size?: 'sm' | 'md';
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  size = 'md',
  className = '',
}) => {
  const normalized = status.toLowerCase() as OperationalStatus;

  const config = {
    healthy: {
      bg: 'bg-emerald-950/60',
      border: 'border-emerald-700/60',
      text: 'text-emerald-400',
      dot: 'bg-emerald-400',
      defaultLabel: 'HEALTHY',
    },
    warning: {
      bg: 'bg-amber-950/60',
      border: 'border-amber-700/60',
      text: 'text-amber-400',
      dot: 'bg-amber-400',
      defaultLabel: 'WARNING',
    },
    degraded: {
      bg: 'bg-amber-950/60',
      border: 'border-amber-700/60',
      text: 'text-amber-400',
      dot: 'bg-amber-400',
      defaultLabel: 'DEGRADED',
    },
    critical: {
      bg: 'bg-rose-950/60',
      border: 'border-rose-700/60',
      text: 'text-rose-400',
      dot: 'bg-rose-400',
      defaultLabel: 'CRITICAL',
    },
    offline: {
      bg: 'bg-slate-900',
      border: 'border-slate-700',
      text: 'text-slate-400',
      dot: 'bg-slate-500',
      defaultLabel: 'OFFLINE',
    },
    unknown: {
      bg: 'bg-slate-900',
      border: 'border-slate-700',
      text: 'text-slate-400',
      dot: 'bg-slate-500',
      defaultLabel: 'UNKNOWN',
    },
  }[normalized] || {
    bg: 'bg-slate-900',
    border: 'border-slate-700',
    text: 'text-slate-400',
    dot: 'bg-slate-500',
    defaultLabel: status.toUpperCase(),
  };

  const displayText = label || config.defaultLabel;
  const isSm = size === 'sm';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono font-medium border rounded ${
        isSm ? 'px-1.5 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'
      } ${config.bg} ${config.border} ${config.text} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} aria-hidden="true" />
      <span>{displayText}</span>
    </span>
  );
};

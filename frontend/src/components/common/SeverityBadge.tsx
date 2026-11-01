import React from 'react';
import { IncidentSeverity } from '@/types/api';

export interface SeverityBadgeProps {
  severity: IncidentSeverity | string;
  size?: 'sm' | 'md';
  className?: string;
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({
  severity,
  size = 'md',
  className = '',
}) => {
  const normalized = severity.toUpperCase();

  const config = {
    CRITICAL: {
      bg: 'bg-rose-950/80',
      border: 'border-rose-600/80',
      text: 'text-rose-300',
      dot: 'bg-rose-500',
    },
    MAJOR: {
      bg: 'bg-orange-950/80',
      border: 'border-orange-600/80',
      text: 'text-orange-300',
      dot: 'bg-orange-500',
    },
    MINOR: {
      bg: 'bg-amber-950/80',
      border: 'border-amber-600/80',
      text: 'text-amber-300',
      dot: 'bg-amber-400',
    },
    WARNING: {
      bg: 'bg-yellow-950/70',
      border: 'border-yellow-600/70',
      text: 'text-yellow-300',
      dot: 'bg-yellow-400',
    },
    INFORMATIONAL: {
      bg: 'bg-blue-950/70',
      border: 'border-blue-600/70',
      text: 'text-blue-300',
      dot: 'bg-blue-400',
    },
  }[normalized] || {
    bg: 'bg-slate-900',
    border: 'border-slate-700',
    text: 'text-slate-300',
    dot: 'bg-slate-400',
  };

  const isSm = size === 'sm';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono font-semibold border rounded tracking-wide ${
        isSm ? 'px-1.5 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'
      } ${config.bg} ${config.border} ${config.text} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} aria-hidden="true" />
      <span>{normalized}</span>
    </span>
  );
};

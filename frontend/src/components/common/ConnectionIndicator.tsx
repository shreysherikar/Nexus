import React from 'react';
import { WsConnectionStatus } from '@/types/websocket';
import { useWebSocketStatus } from '@/websocket/useWebSocket';

export interface ConnectionIndicatorProps {
  status?: WsConnectionStatus;
  showLabel?: boolean;
  className?: string;
}

export const ConnectionIndicator: React.FC<ConnectionIndicatorProps> = ({
  status: propStatus,
  showLabel = true,
  className = '',
}) => {
  const hookStatus = useWebSocketStatus();
  const currentStatus = propStatus ?? hookStatus;

  const config = {
    CONNECTED: {
      color: 'bg-emerald-500',
      text: 'text-emerald-400',
      label: 'CONNECTED',
      description: 'Connected to live telemetry feed',
      badgeBg: 'bg-emerald-950/40 border-emerald-700/50',
    },
    CONNECTING: {
      color: 'bg-sky-400 animate-pulse',
      text: 'text-sky-300',
      label: 'CONNECTING',
      description: 'Negotiating connection',
      badgeBg: 'bg-sky-950/40 border-sky-700/50',
    },
    RECONNECTING: {
      color: 'bg-amber-400 animate-pulse',
      text: 'text-amber-300',
      label: 'RECONNECTING',
      description: 'Backoff reconnecting to event stream',
      badgeBg: 'bg-amber-950/40 border-amber-700/50',
    },
    DISCONNECTED: {
      color: 'bg-slate-500',
      text: 'text-slate-400',
      label: 'DISCONNECTED',
      description: 'Live streaming endpoint disconnected',
      badgeBg: 'bg-slate-900 border-slate-700',
    },
  }[currentStatus] || {
    color: 'bg-slate-500',
    text: 'text-slate-400',
    label: currentStatus,
    description: 'Unknown connection status',
    badgeBg: 'bg-slate-900 border-slate-700',
  };

  return (
    <div
      className={`inline-flex items-center gap-2 px-2.5 py-1 rounded border text-xs font-mono font-medium ${config.badgeBg} ${config.text} ${className}`}
      title={config.description}
      role="status"
      aria-live="polite"
    >
      <span className={`w-2 h-2 rounded-full ${config.color}`} />
      {showLabel && <span>{config.label}</span>}
    </div>
  );
};

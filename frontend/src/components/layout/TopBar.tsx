import React, { useEffect, useState } from 'react';
import { Menu, Shield, RefreshCw } from 'lucide-react';
import { ConnectionIndicator } from '@/components/common/ConnectionIndicator';
import { apiClient } from '@/api/client';

export interface TopBarProps {
  onToggleSidebar?: () => void;
  className?: string;
}

export const TopBar: React.FC<TopBarProps> = ({
  onToggleSidebar,
  className = '',
}) => {
  const [time, setTime] = useState<string>('');
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const checkHealth = async () => {
    try {
      const res = await apiClient.getHealth();
      setBackendHealthy(res.status === 'healthy');
    } catch {
      setBackendHealthy(false);
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header
      className={`h-14 border-b border-noc-border bg-noc-base px-4 flex items-center justify-between gap-4 select-none ${className}`}
      aria-label="Top Bar"
    >
      <div className="flex items-center gap-3">
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className="p-1.5 rounded text-noc-text-secondary hover:text-noc-text-primary hover:bg-noc-surface border border-transparent hover:border-noc-border transition-colors"
            title="Toggle Sidebar Navigation"
            aria-label="Toggle Navigation Sidebar"
          >
            <Menu className="w-4 h-4" />
          </button>
        )}

        <div className="flex items-center gap-2">
          <span className="text-xs font-mono font-bold text-noc-text-primary uppercase tracking-wide">
            NOC CONSOLE
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-blue-950/60 border border-blue-700/50 text-blue-300">
            {import.meta.env?.VITE_NOC_ENV || 'LOCAL ENVIRONMENT'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* Backend REST Health Status */}
        <div
          className="flex items-center gap-1.5 text-xs font-mono cursor-pointer"
          title="Click to check backend REST connectivity"
          onClick={checkHealth}
        >
          <span
            className={`w-2 h-2 rounded-full ${
              backendHealthy === true
                ? 'bg-emerald-500'
                : backendHealthy === false
                ? 'bg-rose-500'
                : 'bg-slate-500'
            }`}
          />
          <span className="text-noc-text-secondary text-[11px]">
            REST: {backendHealthy === true ? 'READY' : backendHealthy === false ? 'DOWN' : 'CHECKING'}
          </span>
          <RefreshCw className="w-2.5 h-2.5 text-noc-text-muted hover:text-noc-text-primary" />
        </div>

        {/* WebSocket Live Connection Indicator */}
        <ConnectionIndicator />

        {/* UTC Clock */}
        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 bg-noc-canvas border border-noc-border rounded font-mono text-xs text-noc-text-secondary">
          <span className="text-noc-text-muted">TIME:</span>
          <span>{time || 'SYNCHRONIZING...'}</span>
        </div>

        {/* Operator Profile Tag */}
        <div className="flex items-center gap-1.5 text-xs font-mono text-noc-text-muted border-l border-noc-border pl-4">
          <Shield className="w-3.5 h-3.5 text-blue-400" />
          <span className="text-noc-text-secondary">
            {import.meta.env?.VITE_OPERATOR_ROLE || 'OPERATOR'}
          </span>
        </div>
      </div>
    </header>
  );
};

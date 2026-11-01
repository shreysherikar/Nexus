import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  MapPin,
  Activity,
  Bell,
  AlertOctagon,
  BarChart3,
  Radio,
  Server,
} from 'lucide-react';
import { NAVIGATION_ITEMS } from '@/types/navigation';

const ICONS: Record<string, React.FC<{ className?: string }>> = {
  LayoutDashboard,
  MapPin,
  Activity,
  Bell,
  AlertOctagon,
  BarChart3,
};

export interface SidebarProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  className?: string;
}

export const Sidebar: React.FC<SidebarProps> = ({
  collapsed = false,
  className = '',
}) => {
  return (
    <aside
      className={`bg-noc-base border-r border-noc-border flex flex-col justify-between select-none transition-all duration-200 ${
        collapsed ? 'w-16' : 'w-64'
      } ${className}`}
      aria-label="Primary Navigation"
    >
      <div>
        {/* Brand Header */}
        <div className="h-14 border-b border-noc-border flex items-center px-4 gap-3 bg-noc-base/90">
          <div className="w-8 h-8 rounded bg-blue-600/20 border border-blue-500/40 flex items-center justify-center shrink-0">
            <Radio className="w-4 h-4 text-blue-400" />
          </div>
          {!collapsed && (
            <div className="flex flex-col min-w-0">
              <span className="font-bold text-sm tracking-wider text-noc-text-primary uppercase font-mono">
                NEXUS<span className="text-blue-500">_NOC</span>
              </span>
              <span className="text-[10px] text-noc-text-muted truncate">
                Network Intelligence v0.1
              </span>
            </div>
          )}
        </div>

        {/* Navigation Section */}
        <div className="p-3">
          {!collapsed && (
            <div className="px-3 pb-2 text-[10px] font-mono font-semibold uppercase text-noc-text-muted tracking-wider">
              Operations Center
            </div>
          )}
          <nav className="flex flex-col gap-1">
            {NAVIGATION_ITEMS.map((item) => {
              const IconComponent = ICONS[item.iconName] || Server;
              return (
                <NavLink
                  key={item.id}
                  to={item.path}
                  title={collapsed ? item.name : undefined}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2 rounded text-xs font-medium transition-colors ${
                      isActive
                        ? 'bg-blue-600/15 text-blue-400 border border-blue-500/30'
                        : 'text-noc-text-secondary hover:text-noc-text-primary hover:bg-noc-surface'
                    } ${collapsed ? 'justify-center px-2' : ''}`
                  }
                >
                  <IconComponent className="w-4 h-4 shrink-0" />
                  {!collapsed && <span className="truncate">{item.name}</span>}
                </NavLink>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Footer System Status */}
      <div className="p-3 border-t border-noc-border bg-noc-base/60">
        {!collapsed ? (
          <div className="flex flex-col gap-1 text-[11px] font-mono text-noc-text-muted">
            <div className="flex items-center justify-between">
              <span>PLATFORM</span>
              <span className="text-slate-300">ONLINE</span>
            </div>
            <div className="flex items-center justify-between">
              <span>SECURITY</span>
              <span className="text-emerald-400">STANDBY</span>
            </div>
          </div>
        ) : (
          <div className="flex justify-center text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>
        )}
      </div>
    </aside>
  );
};

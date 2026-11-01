import React, { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { wsClient } from '@/websocket/client';

export const AppShell: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    wsClient.connect();
    return () => {
      wsClient.disconnect();
    };
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-noc-canvas text-noc-text-primary antialiased">
      {/* Navigation Sidebar */}
      <Sidebar collapsed={collapsed} onToggleCollapse={() => setCollapsed(!collapsed)} />

      {/* Main Execution View */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top Operational Bar */}
        <TopBar onToggleSidebar={() => setCollapsed(!collapsed)} />

        {/* Scrollable Page Body */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 bg-noc-canvas">
          <div className="max-w-7xl mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};

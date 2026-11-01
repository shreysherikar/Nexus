import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { OverviewPage } from '@/pages/OverviewPage';
import { NetworkMapPage } from '@/pages/NetworkMapPage';
import { KpisPage } from '@/pages/KpisPage';
import { AlarmsPage } from '@/pages/AlarmsPage';
import { IncidentsPage } from '@/pages/IncidentsPage';
import { AnalyticsPage } from '@/pages/AnalyticsPage';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="network-map" element={<NetworkMapPage />} />
          <Route path="kpis" element={<KpisPage />} />
          <Route path="alarms" element={<AlarmsPage />} />
          <Route path="incidents" element={<IncidentsPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};

export default App;

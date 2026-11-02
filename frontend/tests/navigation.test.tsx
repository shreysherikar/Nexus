import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { OverviewPage } from '@/pages/OverviewPage';
import { NetworkMapPage } from '@/pages/NetworkMapPage';
import { KpisPage } from '@/pages/KpisPage';
import { AlarmsPage } from '@/pages/AlarmsPage';
import { IncidentsPage } from '@/pages/IncidentsPage';
import { AnalyticsPage } from '@/pages/AnalyticsPage';

vi.mock('@/api/client', () => {
  return {
    apiClient: {
      getHealth: vi.fn().mockResolvedValue({ status: 'healthy' }),
      getIncidents: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
      getIncidentMetrics: vi.fn().mockResolvedValue({
        total_incidents: 0,
        open_incident_count: 0,
        incidents_by_status: {},
        incidents_by_severity: {},
        mtta_seconds: null,
        mttr_seconds: null,
        mttd_seconds: null,
        ack_sla_breached_count: 0,
        resolve_sla_breached_count: 0,
        as_of: new Date().toISOString(),
      }),
      getIncidentTimeline: vi.fn().mockResolvedValue([]),
      getTopology: vi.fn().mockResolvedValue({
        nodes: [
          { node_id: 'CORE-01', node_type: 'CORE', parent_id: null, status: 'ONLINE', latitude: null, longitude: null, children: ['AGG-01', 'AGG-02'] },
          { node_id: 'AGG-01', node_type: 'AGGREGATION', parent_id: 'CORE-01', status: 'ONLINE', latitude: null, longitude: null, children: ['SITE-01'] },
          { node_id: 'AGG-02', node_type: 'AGGREGATION', parent_id: 'CORE-01', status: 'ONLINE', latitude: null, longitude: null, children: ['SITE-04'] },
          { node_id: 'SITE-01', node_type: 'SITE', parent_id: 'AGG-01', status: 'ONLINE', latitude: null, longitude: null, children: ['CELL-01'] },
          { node_id: 'CELL-01', node_type: 'CELL', parent_id: 'SITE-01', status: 'ONLINE', latitude: null, longitude: null, children: [] },
        ],
        total_nodes: 5,
        tiers: { CORE: 1, AGGREGATION: 2, SITE: 1, CELL: 1 },
      }),
      getTopologyNode: vi.fn().mockResolvedValue({
        node_id: 'CORE-01',
        node_type: 'CORE',
        parent_id: null,
        status: 'ONLINE',
        latitude: null,
        longitude: null,
        children: ['AGG-01', 'AGG-02'],
      }),
      getTelemetry: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 }),
      getAlarms: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
      getAlarmById: vi.fn().mockResolvedValue({
        alarm_id: 'ALM-1',
        node_id: 'CELL-01',
        rule_id: 'RULE-1',
        metric_name: 'latency_ms',
        source: 'THRESHOLD',
        severity: 'CRITICAL',
        current_value: 120,
        threshold: 80,
        first_seen: '2026-11-01T10:00:00Z',
        last_seen: '2026-11-01T10:05:00Z',
        observation_count: 5,
        status: 'ACTIVE',
        cleared_at: null,
        description: 'High latency',
        evidence: {},
      }),
      generateTelemetryStep: vi.fn().mockResolvedValue({
        generated_count: 27,
        timestamp: '2026-11-01T14:00:00Z',
        message: 'Step complete',
      }),
      getFaultScenarios: vi.fn().mockResolvedValue({ items: [], total: 0, active_scenario_id: null }),
      getActiveFaultScenario: vi.fn().mockResolvedValue({
        active: false,
        scenario_id: null,
        scenario_key: null,
        name: null,
        description: null,
        faults: [],
        activated_at: null,
      }),
      activateFaultScenario: vi.fn().mockResolvedValue({
        success: true,
        message: 'Activated',
        active_scenario: {
          active: true,
          scenario_id: 'scen-1',
          scenario_key: 'cell_outage',
          name: 'Cell Outage',
          description: '',
          faults: [],
          activated_at: '2026-11-01T12:00:00Z',
        },
      }),
      deactivateFaultScenario: vi.fn().mockResolvedValue({
        success: true,
        message: 'Deactivated',
        active_scenario: {
          active: false,
          scenario_id: null,
          scenario_key: null,
          name: null,
          description: null,
          faults: [],
          activated_at: null,
        },
      }),
    },
  };
});

function renderWithRouter(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
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
    </MemoryRouter>
  );
}

describe('Application Shell and Route Navigation', () => {
  it('redirects root / to /overview and renders overview content', async () => {
    renderWithRouter('/');
    expect(await screen.findByText('Network Operations Center Overview')).toBeInTheDocument();
    expect(screen.getByText(/NEXUS/)).toBeInTheDocument();
    expect(screen.getByText('Authoritative Network Health Summary')).toBeInTheDocument();
  });

  it('navigates to /network-map and renders network map page structure', async () => {
    renderWithRouter('/network-map');
    expect(await screen.findByText('Network Topology & Geographic Hierarchy')).toBeInTheDocument();
    expect(screen.getByText('Logical Hierarchy')).toBeInTheDocument();
    expect(screen.getByText('Geographic Map')).toBeInTheDocument();
    const coreNodes = await screen.findAllByText('CORE-01');
    expect(coreNodes.length).toBeGreaterThan(0);
  });

  it('navigates to /kpis and renders telemetry page structure', async () => {
    renderWithRouter('/kpis');
    expect(await screen.findByText('KPI Monitoring & Telemetry Stream')).toBeInTheDocument();
    expect(screen.getByText('Generate One Telemetry Step')).toBeInTheDocument();
    expect(screen.getByText(/Simulated Network Telemetry Engine/)).toBeInTheDocument();
  });

  it('navigates to /alarms and renders alarm inventory page structure', async () => {
    renderWithRouter('/alarms');
    expect(await screen.findByText('Network Alarms Inventory')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Filter by Node ID...')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Filter by Rule ID...')).toBeInTheDocument();
  });

  it('navigates to /incidents and renders incident tracking page structure', async () => {
    renderWithRouter('/incidents');
    expect(await screen.findByText('Incident Operations & Lifecycle Workspace')).toBeInTheDocument();
    expect(screen.getByText('All Statuses')).toBeInTheDocument();
  });

  it('navigates to /analytics and renders analytics page structure', async () => {
    renderWithRouter('/analytics');
    expect(await screen.findByText('Incident Analytics & Operational SLA Tracking')).toBeInTheDocument();
    expect(screen.getByText('Overall SLA Compliance')).toBeInTheDocument();
  });
});

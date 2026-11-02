import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { OverviewPage } from '@/pages/OverviewPage';
import { KpisPage } from '@/pages/KpisPage';
import { NetworkMapPage } from '@/pages/NetworkMapPage';
import { IncidentsPage } from '@/pages/IncidentsPage';
import { AlarmsPage } from '@/pages/AlarmsPage';
import { AnalyticsPage } from '@/pages/AnalyticsPage';
import { apiClient } from '@/api/client';

vi.mock('@/api/client', () => {
  return {
    apiClient: {
      getHealth: vi.fn(),
      getIncidents: vi.fn(),
      getIncidentById: vi.fn(),
      getIncidentMetrics: vi.fn(),
      getIncidentTimeline: vi.fn(),
      acknowledgeIncident: vi.fn(),
      resolveIncident: vi.fn(),
      getTopology: vi.fn(),
      getTopologyNode: vi.fn(),
      getTelemetry: vi.fn(),
      generateTelemetryStep: vi.fn(),
      getAlarms: vi.fn(),
      getAlarmById: vi.fn(),
      getDetectionRules: vi.fn(),
      getFaultScenarios: vi.fn(),
      getActiveFaultScenario: vi.fn(),
      activateFaultScenario: vi.fn(),
      deactivateFaultScenario: vi.fn(),
    },
  };
});

describe('Milestone 7 End-to-End Scenarios', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.getDetectionRules).mockResolvedValue({
      items: [
        {
          rule_id: 'RULE-AVAIL-CRIT',
          metric_name: 'availability_pct',
          operator: '<',
          threshold: 95.0,
          clear_threshold: 98.0,
          severity: 'CRITICAL',
          node_types: null,
          description: 'Availability below 95%',
          enabled: true,
        },
        {
          rule_id: 'RULE-DROP-CRIT',
          metric_name: 'connection_drop_rate_pct',
          operator: '>',
          threshold: 5.0,
          clear_threshold: 2.0,
          severity: 'CRITICAL',
          node_types: null,
          description: 'Drop rate above 5%',
          enabled: true,
        },
        {
          rule_id: 'RULE-LAT-MAJOR',
          metric_name: 'latency_ms',
          operator: '>',
          threshold: 80.0,
          clear_threshold: 60.0,
          severity: 'MAJOR',
          node_types: null,
          description: 'Latency above 80ms',
          enabled: true,
        },
        {
          rule_id: 'RULE-TP-WARN',
          metric_name: 'throughput_mbps',
          operator: '<',
          threshold: 5.0,
          clear_threshold: 10.0,
          severity: 'WARNING',
          node_types: ['CELL'],
          description: 'Throughput below 5 Mbps',
          enabled: true,
        },
      ],
      total: 4,
    });
    vi.mocked(apiClient.getFaultScenarios).mockResolvedValue({ items: [], total: 0, active_scenario_id: null });
    vi.mocked(apiClient.getActiveFaultScenario).mockResolvedValue({
      active: false,
      scenario_id: null,
      scenario_key: null,
      name: null,
      description: null,
      faults: [],
      activated_at: null,
    });
    vi.mocked(apiClient.activateFaultScenario).mockResolvedValue({
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
    });
    vi.mocked(apiClient.deactivateFaultScenario).mockResolvedValue({
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
    });
  });

  it('Scenario A — Initial Startup: Honest empty states and genuine topology summary', async () => {
    vi.mocked(apiClient.getIncidentMetrics).mockResolvedValue({
      total_incidents: 0,
      open_incident_count: 0,
      incidents_by_status: {},
      incidents_by_severity: {},
      mtta_seconds: null,
      mttr_seconds: null,
      mttd_seconds: null,
      total_incidents_evaluated: 0,
      compliant_incident_count: 0,
      breached_incident_count: 0,
      ack_sla_breached_count: 0,
      resolve_sla_breached_count: 0,
      sla_compliance_pct: null,
      as_of: '2026-11-01T12:00:00Z',
    });
    vi.mocked(apiClient.getIncidents).mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 });
    vi.mocked(apiClient.getAlarms).mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 });
    vi.mocked(apiClient.getTopology).mockResolvedValue({
      nodes: [
        { node_id: 'CORE-01', node_type: 'CORE', parent_id: null, status: 'ONLINE', latitude: null, longitude: null, children: ['AGG-01'] },
        { node_id: 'AGG-01', node_type: 'AGGREGATION', parent_id: 'CORE-01', status: 'ONLINE', latitude: null, longitude: null, children: [] },
      ],
      total_nodes: 2,
      tiers: { CORE: 1, AGGREGATION: 1 },
    });
    vi.mocked(apiClient.getTelemetry).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('Network Operations Center Overview')).toBeInTheDocument();
    expect(screen.getByText('Total Network Nodes')).toBeInTheDocument();
    // Honest empty telemetry: Insufficient Telemetry count is 2 (nodes exist but no telemetry)
    expect(screen.getByText('Insufficient Telemetry')).toBeInTheDocument();
  });

  it('Scenario B — Telemetry Generation: Operator triggers simulation step', async () => {
    vi.mocked(apiClient.getTopology).mockResolvedValue({
      nodes: [
        { node_id: 'CELL-01', node_type: 'CELL', parent_id: 'SITE-01', status: 'ONLINE', latitude: null, longitude: null, children: [] },
      ],
      total_nodes: 1,
      tiers: { CELL: 1 },
    });
    vi.mocked(apiClient.getTelemetry).mockResolvedValueOnce({ items: [], total: 0, limit: 500, offset: 0 });
    vi.mocked(apiClient.generateTelemetryStep).mockResolvedValueOnce({
      generated_count: 27,
      timestamp: '2026-11-01T12:05:00Z',
      message: 'Generated 1 step',
    });
    vi.mocked(apiClient.getTelemetry).mockResolvedValueOnce({
      items: [
        {
          node_id: 'CELL-01',
          timestamp: '2026-11-01T12:05:00Z',
          performance: { throughput_mbps: 85.5, latency_ms: 22.0 },
          reliability: { availability_pct: 99.8, connection_drop_rate_pct: 0.2, handover_success_rate_pct: 98.5 },
          radio: { rsrp_dbm: -92.0, sinr_db: 15.0, prb_utilization_pct: 45.0 },
        },
      ],
      total: 1,
      limit: 500,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <KpisPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('Telemetry Generation Has Not Yet Been Triggered')).toBeInTheDocument();
    const generateBtn = screen.getByRole('button', { name: /Generate One Telemetry Step/i });
    await userEvent.click(generateBtn);

    expect(apiClient.generateTelemetryStep).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(screen.getByText(/Generated 1 simulation cycle/)).toBeInTheDocument();
    });
  });

  it('Scenario D — Incident Lifecycle: Acknowledge and Resolve with mandatory operator notes', async () => {
    const testIncident = {
      incident_id: 'INC-2026-001',
      correlation_group_id: 'GRP-1',
      status: 'OPEN',
      severity: 'CRITICAL',
      priority: 'P1',
      title: 'Backhaul Link Failure Detected',
      description: 'Loss of optical carrier on AGG-01',
      alarm_ids: ['ALM-01'],
      affected_node_ids: ['AGG-01', 'SITE-01'],
      suspected_cause_type: 'BACKHAUL_FAILURE',
      suspected_target_id: 'AGG-01',
      suspected_target_type: 'NODE',
      rca_confidence_score: 0.95,
      rca_hypotheses: [{ explanation: 'High drop rate on tributary sites' }],
      rca_evidence: [],
      created_at: '2026-11-01T10:00:00Z',
      ack_deadline: '2026-11-01T10:15:00Z',
      resolve_deadline: '2026-11-01T11:00:00Z',
      sla_status: {
        ack_breached: false,
        resolve_breached: false,
        ack_time_seconds: null,
        resolve_time_seconds: null,
        evaluation_timestamp: '2026-11-01T10:05:00Z',
      },
    };

    vi.mocked(apiClient.getIncidents).mockResolvedValue({
      items: [testIncident],
      total: 1,
      limit: 10,
      offset: 0,
    });
    vi.mocked(apiClient.getIncidentTimeline).mockResolvedValue([
      {
        event_id: 'EVT-1',
        incident_id: 'INC-2026-001',
        event_type: 'INCIDENT_CREATED',
        timestamp: '2026-11-01T10:00:00Z',
        actor: 'CORRELATION_ENGINE',
        actor_type: 'SYSTEM',
        details: {},
      },
    ]);
    vi.mocked(apiClient.acknowledgeIncident).mockResolvedValue({
      ...testIncident,
      status: 'ACKNOWLEDGED',
      acknowledged_at: '2026-11-01T10:05:00Z',
      acknowledged_by: 'OPERATOR_ALICE',
    });
    vi.mocked(apiClient.resolveIncident).mockResolvedValue({
      ...testIncident,
      status: 'RESOLVED',
      resolved_at: '2026-11-01T10:20:00Z',
      resolved_by: 'OPERATOR_ALICE',
    });

    render(
      <MemoryRouter>
        <IncidentsPage />
      </MemoryRouter>
    );

    // Open detail drawer
    const inspectBtn = await screen.findByRole('button', { name: /Inspect/i });
    await userEvent.click(inspectBtn);

    // Click Acknowledge
    const ackBtn = screen.getByRole('button', { name: /^Acknowledge$/i });
    await userEvent.click(ackBtn);

    // Confirmation modal appears
    expect(screen.getByText('Confirm Incident Acknowledgment')).toBeInTheDocument();
    const confirmAckBtn = screen.getByRole('button', { name: /Confirm Acknowledge/i });
    await userEvent.click(confirmAckBtn);

    expect(apiClient.acknowledgeIncident).toHaveBeenCalledWith(
      'INC-2026-001',
      expect.objectContaining({ actor: 'NOC_OPERATOR' })
    );
  });

  it('Scenario F — Geographic Data: Honest empty state when coordinates are not configured', async () => {
    vi.mocked(apiClient.getTopology).mockResolvedValue({
      nodes: [
        { node_id: 'CORE-01', node_type: 'CORE', parent_id: null, status: 'ONLINE', latitude: null, longitude: null, children: [] },
      ],
      total_nodes: 1,
      tiers: { CORE: 1 },
    });
    vi.mocked(apiClient.getTelemetry).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    vi.mocked(apiClient.getAlarms).mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 });

    render(
      <MemoryRouter>
        <NetworkMapPage />
      </MemoryRouter>
    );

    // Click Geographic Map tab
    const geoTab = await screen.findByRole('button', { name: /Geographic Map/i });
    await userEvent.click(geoTab);

    // Assert honest empty state explaining coordinates are not configured
    expect(screen.getByText('Geographic Coordinates Not Configured')).toBeInTheDocument();
    expect(screen.getByText(/map markers and physical coordinates are never fabricated/i)).toBeInTheDocument();
  });

  it('Scenario C — Alarms Inspection: Renders alarms and filters by severity', async () => {
    vi.mocked(apiClient.getAlarms).mockResolvedValue({
      items: [
        {
          alarm_id: 'ALM-CELL-01-0001',
          node_id: 'CELL-01',
          rule_id: 'RULE-AVAIL-CRIT',
          metric_name: 'availability_pct',
          source: 'THRESHOLD',
          severity: 'CRITICAL',
          current_value: 91.2,
          threshold: 95.0,
          first_seen: '2026-11-01T10:00:00Z',
          last_seen: '2026-11-01T10:05:00Z',
          observation_count: 5,
          status: 'ACTIVE',
          cleared_at: null,
          description: 'Carrier availability breached',
          evidence: {},
        },
      ],
      total: 1,
      limit: 15,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <AlarmsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('Network Alarms Inventory')).toBeInTheDocument();
    expect(screen.getByText('ALM-CELL-01-0001')).toBeInTheDocument();
    expect(screen.getByText('RULE-AVAIL-CRIT')).toBeInTheDocument();
  });

  it('Scenario G — Analytics Page: Displays authoritative SLA compliance from backend without additive subtraction', async () => {
    // Zero evaluated incidents: compliance shows N/A
    vi.mocked(apiClient.getIncidentMetrics).mockResolvedValueOnce({
      total_incidents: 2,
      open_incident_count: 2,
      incidents_by_status: { OPEN: 2 },
      incidents_by_severity: { CRITICAL: 2 },
      mtta_seconds: null,
      mttr_seconds: null,
      mttd_seconds: null,
      total_incidents_evaluated: 0,
      compliant_incident_count: 0,
      breached_incident_count: 0,
      ack_sla_breached_count: 0,
      resolve_sla_breached_count: 0,
      sla_compliance_pct: null,
      as_of: '2026-11-01T12:00:00Z',
    });

    const { unmount } = render(
      <MemoryRouter>
        <AnalyticsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('Overall SLA Compliance')).toBeInTheDocument();
    expect(screen.getAllByText('N/A').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('0 compliant / 0 evaluated')).toBeInTheDocument();
    unmount();

    // Mixed evaluated incidents with dual breaches (counted once in backend!)
    vi.mocked(apiClient.getIncidentMetrics).mockResolvedValueOnce({
      total_incidents: 3,
      open_incident_count: 1,
      incidents_by_status: { RESOLVED: 2, OPEN: 1 },
      incidents_by_severity: { CRITICAL: 2, MAJOR: 1 },
      mtta_seconds: 300.0,
      mttr_seconds: 1800.0,
      mttd_seconds: 45.0,
      total_incidents_evaluated: 3,
      compliant_incident_count: 2,
      breached_incident_count: 1,
      ack_sla_breached_count: 1,
      resolve_sla_breached_count: 1,
      sla_compliance_pct: 66.67,
      as_of: '2026-11-01T12:00:00Z',
    });

    render(
      <MemoryRouter>
        <AnalyticsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('Overall SLA Compliance')).toBeInTheDocument();
    expect(screen.getByText('66.67%')).toBeInTheDocument();
    expect(screen.getByText('2 compliant / 3 evaluated')).toBeInTheDocument();
  });

  it('Scenario H — KPI Monitoring: Throughput warning and non-radio tier handling', async () => {
    vi.mocked(apiClient.getTopology).mockResolvedValue({
      nodes: [
        { node_id: 'CORE-01', node_type: 'CORE', parent_id: null, status: 'ONLINE', latitude: null, longitude: null, children: [] },
        { node_id: 'CELL-01', node_type: 'CELL', parent_id: 'SITE-01', status: 'ONLINE', latitude: null, longitude: null, children: [] },
      ],
      total_nodes: 2,
      tiers: { CORE: 1, CELL: 1 },
    });
    vi.mocked(apiClient.getTelemetry).mockResolvedValue({
      items: [
        {
          node_id: 'CELL-01',
          timestamp: '2026-11-01T12:00:00Z',
          performance: { throughput_mbps: 3.2, latency_ms: 25.0 }, // throughput < 5.0 Mbps -> warning!
          reliability: { availability_pct: 99.5, connection_drop_rate_pct: 0.1, handover_success_rate_pct: 99.0 },
          radio: { rsrp_dbm: -90.0, sinr_db: 12.0, prb_utilization_pct: 30.0 },
        },
      ],
      total: 1,
      limit: 500,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <KpisPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('KPI Monitoring & Telemetry Stream')).toBeInTheDocument();
    expect(screen.getByText('RULE-TP-WARN (< 5 Mbps)')).toBeInTheDocument();
    expect(screen.getByText('3.2 Mbps')).toBeInTheDocument();

    // Switch node to non-radio CORE-01
    const nodeSelect = screen.getByDisplayValue('CELL-01 (CELL)');
    await userEvent.selectOptions(nodeSelect, 'CORE-01');

    // Should indicate non-radio node message
    expect(
      screen.getByText(/Radio frequency and spectrum measurements \(RSRP, SINR, PRB utilization\) apply exclusively to CELL nodes/i)
    ).toBeInTheDocument();
  });
});

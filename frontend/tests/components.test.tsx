import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StatusBadge } from '@/components/common/StatusBadge';
import { SeverityBadge } from '@/components/common/SeverityBadge';
import { MetricCard } from '@/components/common/MetricCard';
import { ConnectionIndicator } from '@/components/common/ConnectionIndicator';
import { DataTable } from '@/components/common/DataTable';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { SimpleLineChart } from '@/components/common/SimpleLineChart';
import { BarChartDistribution } from '@/components/common/BarChartDistribution';
import { FaultInjectionPanel } from '@/components/common/FaultInjectionPanel';
import { apiClient } from '@/api/client';

describe('Design System Components', () => {
  it('renders StatusBadge with accessible text label and correct styling', () => {
    const { rerender } = render(<StatusBadge status="healthy" />);
    expect(screen.getByText('HEALTHY')).toBeInTheDocument();

    rerender(<StatusBadge status="critical" label="OUTAGE" />);
    expect(screen.getByText('OUTAGE')).toBeInTheDocument();

    rerender(<StatusBadge status="degraded" />);
    expect(screen.getByText('DEGRADED')).toBeInTheDocument();
  });

  it('renders SeverityBadge with standardized severity tokens', () => {
    const { rerender } = render(<SeverityBadge severity="CRITICAL" />);
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();

    rerender(<SeverityBadge severity="MAJOR" />);
    expect(screen.getByText('MAJOR')).toBeInTheDocument();

    rerender(<SeverityBadge severity="INFORMATIONAL" />);
    expect(screen.getByText('INFORMATIONAL')).toBeInTheDocument();
  });

  it('renders ConnectionIndicator with live WebSocket status', () => {
    const { rerender } = render(<ConnectionIndicator status="CONNECTED" />);
    expect(screen.getByText('CONNECTED')).toBeInTheDocument();

    rerender(<ConnectionIndicator status="DISCONNECTED" />);
    expect(screen.getByText('DISCONNECTED')).toBeInTheDocument();

    rerender(<ConnectionIndicator status="RECONNECTING" />);
    expect(screen.getByText('RECONNECTING')).toBeInTheDocument();

    rerender(<ConnectionIndicator status="CONNECTING" />);
    expect(screen.getByText('CONNECTING')).toBeInTheDocument();
  });

  it('renders MetricCard with stat, subtitle, and delta', () => {
    render(
      <MetricCard
        title="Active Incidents"
        value={12}
        unit="P1-P3"
        subtitle="Across 4 sites"
        delta={{ value: '2', isPositive: false, label: 'vs last hour' }}
      />
    );
    expect(screen.getByText('Active Incidents')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('P1-P3')).toBeInTheDocument();
    expect(screen.getByText('Across 4 sites')).toBeInTheDocument();
    expect(screen.getByText(/2 vs last hour/)).toBeInTheDocument();
  });

  it('renders DataTable with columns and data rows', async () => {
    const data = [
      { id: '1', name: 'CORE-01', tier: 'CORE' },
      { id: '2', name: 'AGG-01', tier: 'AGGREGATION' },
    ];
    const columns = [
      { key: 'name', header: 'Node Name' },
      { key: 'tier', header: 'Topology Tier' },
    ];
    const onRowClick = vi.fn();

    render(
      <DataTable
        columns={columns}
        data={data}
        keyExtractor={(item) => item.id}
        onRowClick={onRowClick}
      />
    );

    expect(screen.getByText('CORE-01')).toBeInTheDocument();
    expect(screen.getByText('AGG-01')).toBeInTheDocument();

    await userEvent.click(screen.getByText('CORE-01'));
    expect(onRowClick).toHaveBeenCalledWith(data[0]);
  });

  it('renders EmptyState with honest description and action button', async () => {
    const onAction = vi.fn();
    render(
      <EmptyState
        title="No Alarms Pending"
        description="All monitored metrics are within SLA tolerance."
        action={{ label: 'Refresh Feed', onClick: onAction }}
      />
    );

    expect(screen.getByText('No Alarms Pending')).toBeInTheDocument();
    expect(screen.getByText('All monitored metrics are within SLA tolerance.')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Refresh Feed'));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('renders ErrorState with retry button and error details', async () => {
    const onRetry = vi.fn();
    render(
      <ErrorState
        title="Backend Failure"
        message="HTTP 500 Internal Server Error"
        details="Database connection timeout after 5000ms"
        onRetry={onRetry}
      />
    );

    expect(screen.getByText('Backend Failure')).toBeInTheDocument();
    expect(screen.getByText('HTTP 500 Internal Server Error')).toBeInTheDocument();
    expect(screen.getByText('Database connection timeout after 5000ms')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Retry Operation'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('renders SimpleLineChart empty and single observation states honestly', () => {
    const { rerender } = render(<SimpleLineChart data={[]} metricName="latency_ms" />);
    expect(screen.getByText(/No stored telemetry observations for latency_ms/i)).toBeInTheDocument();

    rerender(
      <SimpleLineChart
        data={[{ timestamp: '2026-11-01T12:00:00Z', value: 45.2 }]}
        metricName="latency_ms"
        unit="ms"
        threshold={80.0}
        thresholdLabel="Major"
      />
    );
    expect(screen.getByText('Single Discrete Observation')).toBeInTheDocument();
    expect(screen.getByText('45.20')).toBeInTheDocument();
    expect(screen.getByText('Major: 80.00 ms')).toBeInTheDocument();
  });

  it('renders BarChartDistribution with categories and percentages', () => {
    render(
      <BarChartDistribution
        title="Severity Breakdown"
        categories={[
          { key: 'CRITICAL', label: 'Critical', value: 3, color: '#ef4444' },
          { key: 'MAJOR', label: 'Major', value: 7, color: '#f97316' },
        ]}
        total={10}
      />
    );

    expect(screen.getByText('Severity Breakdown')).toBeInTheDocument();
    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(screen.getByText('(30%)')).toBeInTheDocument();
    expect(screen.getByText('Major')).toBeInTheDocument();
    expect(screen.getByText('(70%)')).toBeInTheDocument();
  });

  it('renders FaultInjectionPanel with reference scenarios and active state controls', async () => {
    vi.spyOn(apiClient, 'getFaultScenarios').mockResolvedValue({
      total: 2,
      active_scenario_id: null,
      items: [
        {
          id: 'radio_interference',
          scenario_id: 'SCENARIO-INTERFERENCE-01',
          name: 'Radio RF Interference',
          description: 'Severe external RF interference on CELL-05',
          fault_type: 'RADIO_INTERFERENCE',
          target_id: 'CELL-05',
          severity: 0.8,
          affected_nodes: ['CELL-05'],
          is_active: false,
        },
        {
          id: 'cell_outage',
          scenario_id: 'SCENARIO-CELL-OUTAGE-01',
          name: 'Single Cell Outage',
          description: 'Single radio sector failure on CELL-01',
          fault_type: 'CELL_OUTAGE',
          target_id: 'CELL-01',
          severity: 1.0,
          affected_nodes: ['CELL-01'],
          is_active: false,
        },
      ],
    });

    vi.spyOn(apiClient, 'getActiveFaultScenario').mockResolvedValue({
      active: false,
      scenario_id: null,
      scenario_key: null,
      name: null,
      description: null,
      faults: [],
      activated_at: null,
    });

    render(<FaultInjectionPanel />);

    expect(await screen.findByText('Fault Injection & Controlled Simulation')).toBeInTheDocument();
    expect(screen.getByText(/NETWORK NOMINAL/)).toBeInTheDocument();
    expect(screen.getByText('Radio RF Interference')).toBeInTheDocument();
    expect(screen.getByText('Single Cell Outage')).toBeInTheDocument();
    expect(screen.getByText('Trigger Simulation Step')).toBeInTheDocument();
  });
});

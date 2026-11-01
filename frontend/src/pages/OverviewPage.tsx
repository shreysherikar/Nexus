import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  Bell,
  CheckCircle2,
  Clock,
  HelpCircle,
  Network,
  Radio,
  RefreshCw,
  Server,
  ShieldAlert,
  WifiOff,
} from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { MetricCard } from '@/components/common/MetricCard';
import { DataTable } from '@/components/common/DataTable';
import { SeverityBadge } from '@/components/common/SeverityBadge';
import { OperationalStatus, StatusBadge } from '@/components/common/StatusBadge';
import { ErrorState } from '@/components/common/ErrorState';
import { BarChartDistribution } from '@/components/common/BarChartDistribution';
import { apiClient } from '@/api/client';
import {
  AlarmResponse,
  IncidentMetricsResponse,
  IncidentResponse,
  KPISnapshotResponse,
  TopologyResponse,
} from '@/types/api';
import { useWebSocketSubscription } from '@/websocket/useWebSocket';
import { WsEventType } from '@/types/websocket';

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return 'N/A';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const remSec = Math.round(seconds % 60);
  return remSec > 0 ? `${mins}m ${remSec}s` : `${mins}m`;
}

export type HealthCategory = 'healthy' | 'degraded' | 'offline' | 'unknown' | 'insufficient_telemetry';

export const OverviewPage: React.FC = () => {
  const navigate = useNavigate();

  const [metrics, setMetrics] = useState<IncidentMetricsResponse | null>(null);
  const [recentIncidents, setRecentIncidents] = useState<IncidentResponse[]>([]);
  const [recentAlarms, setRecentAlarms] = useState<AlarmResponse[]>([]);
  const [activeAlarmsCount, setActiveAlarmsCount] = useState<number>(0);
  const [criticalAlarmsCount, setCriticalAlarmsCount] = useState<number>(0);
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [telemetrySnapshots, setTelemetrySnapshots] = useState<KPISnapshotResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<string>('');

  const fetchOverviewData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mRes, incRes, alarmsRes, activeAlarmsRes, topoRes, telemRes] = await Promise.all([
        apiClient.getIncidentMetrics(),
        apiClient.getIncidents({ limit: 5, offset: 0 }),
        apiClient.getAlarms({ limit: 5, offset: 0 }),
        apiClient.getAlarms({ status: 'ACTIVE', limit: 100 }),
        apiClient.getTopology(),
        apiClient.getTelemetry({ limit: 100 }),
      ]);

      setMetrics(mRes);
      setRecentIncidents(incRes.items);
      setRecentAlarms(alarmsRes.items);
      setActiveAlarmsCount(activeAlarmsRes.total);
      setCriticalAlarmsCount(activeAlarmsRes.items.filter((a) => a.severity === 'CRITICAL').length);
      setTopology(topoRes);
      setTelemetrySnapshots(telemRes.items);
      setLastRefreshed(new Date().toISOString());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query operational data';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverviewData();
  }, [fetchOverviewData]);

  // Live WebSocket event listeners: reconcile state without full page flash
  useWebSocketSubscription(WsEventType.INCIDENT_CREATED, () => {
    fetchOverviewData();
  });
  useWebSocketSubscription(WsEventType.INCIDENT_ACKNOWLEDGED, () => {
    fetchOverviewData();
  });
  useWebSocketSubscription(WsEventType.INCIDENT_RESOLVED, () => {
    fetchOverviewData();
  });
  useWebSocketSubscription(WsEventType.ALARM_CREATED, () => {
    fetchOverviewData();
  });
  useWebSocketSubscription(WsEventType.ALARM_UPDATED, () => {
    fetchOverviewData();
  });
  useWebSocketSubscription(WsEventType.ALARM_CLEARED, () => {
    fetchOverviewData();
  });
  useWebSocketSubscription(WsEventType.TOPOLOGY_STATUS_CHANGED, () => {
    fetchOverviewData();
  });
  useWebSocketSubscription(WsEventType.TELEMETRY_SNAPSHOT, () => {
    // Refresh telemetry silently
    apiClient.getTelemetry({ limit: 100 }).then((res) => {
      setTelemetrySnapshots(res.items);
    }).catch(() => {});
  });

  // Calculate Node Health Summary
  const nodeHealthCounts = React.useMemo(() => {
    const summary: Record<HealthCategory, number> = {
      healthy: 0,
      degraded: 0,
      offline: 0,
      unknown: 0,
      insufficient_telemetry: 0,
    };

    if (!topology || topology.nodes.length === 0) {
      return summary;
    }

    // Map latest telemetry per node
    const latestTelemetryByNode = new Map<string, KPISnapshotResponse>();
    for (const snap of telemetrySnapshots) {
      if (!latestTelemetryByNode.has(snap.node_id)) {
        latestTelemetryByNode.set(snap.node_id, snap);
      }
    }

    for (const node of topology.nodes) {
      if (node.status === 'OFFLINE') {
        summary.offline += 1;
        continue;
      }
      if (node.status === 'DEGRADED') {
        summary.degraded += 1;
        continue;
      }
      if (node.status === 'MAINTENANCE') {
        summary.degraded += 1;
        continue;
      }

      const telem = latestTelemetryByNode.get(node.node_id);
      if (!telem) {
        // Honest representation: missing telemetry does NOT equal healthy
        summary.insufficient_telemetry += 1;
        continue;
      }

      // Check genuine reliability telemetry measurements
      const avail = telem.reliability?.availability_pct ?? 0;
      const dropRate = telem.reliability?.connection_drop_rate_pct ?? 0;

      if (avail < 95.0 || dropRate > 3.0) {
        summary.degraded += 1;
      } else if (avail >= 99.0 && dropRate < 1.0) {
        summary.healthy += 1;
      } else {
        summary.degraded += 1;
      }
    }

    return summary;
  }, [topology, telemetrySnapshots]);

  const totalSlaBreaches = metrics
    ? metrics.ack_sla_breached_count + metrics.resolve_sla_breached_count
    : 0;

  const acknowledgedCount = metrics?.incidents_by_status?.['ACKNOWLEDGED'] ?? 0;

  // Severity Distribution Data
  const severityDistribution = [
    {
      key: 'CRITICAL',
      label: 'Critical',
      value: metrics?.incidents_by_severity?.['CRITICAL'] ?? 0,
      color: '#ef4444', // red-500
    },
    {
      key: 'MAJOR',
      label: 'Major',
      value: metrics?.incidents_by_severity?.['MAJOR'] ?? 0,
      color: '#f97316', // orange-500
    },
    {
      key: 'MINOR',
      label: 'Minor',
      value: metrics?.incidents_by_severity?.['MINOR'] ?? 0,
      color: '#eab308', // yellow-500
    },
    {
      key: 'WARNING',
      label: 'Warning',
      value: metrics?.incidents_by_severity?.['WARNING'] ?? 0,
      color: '#f59e0b', // amber-500
    },
  ];

  // Status Distribution Data
  const statusDistribution = [
    {
      key: 'OPEN',
      label: 'Open',
      value: metrics?.incidents_by_status?.['OPEN'] ?? 0,
      color: '#ef4444',
    },
    {
      key: 'ACKNOWLEDGED',
      label: 'Acknowledged',
      value: metrics?.incidents_by_status?.['ACKNOWLEDGED'] ?? 0,
      color: '#f59e0b',
    },
    {
      key: 'RESOLVED',
      label: 'Resolved',
      value: metrics?.incidents_by_status?.['RESOLVED'] ?? 0,
      color: '#10b981',
    },
  ];

  const incidentColumns = [
    {
      key: 'incident_id',
      header: 'Incident ID',
      isMono: true,
      render: (inc: IncidentResponse) => (
        <span
          className="font-mono text-blue-400 font-semibold cursor-pointer hover:underline"
          onClick={() => navigate(`/incidents?id=${encodeURIComponent(inc.incident_id)}`)}
        >
          {inc.incident_id}
        </span>
      ),
    },
    {
      key: 'severity',
      header: 'Severity',
      render: (inc: IncidentResponse) => <SeverityBadge severity={inc.severity} size="sm" />,
    },
    {
      key: 'status',
      header: 'Status',
      render: (inc: IncidentResponse) => (
        <StatusBadge status={inc.status.toLowerCase() as OperationalStatus} size="sm" />
      ),
    },
    {
      key: 'title',
      header: 'Summary',
      render: (inc: IncidentResponse) => (
        <div className="max-w-xs truncate" title={inc.title}>
          <span className="text-noc-text-primary font-medium">{inc.title}</span>
        </div>
      ),
    },
    {
      key: 'created_at',
      header: 'Triggered',
      isMono: true,
      align: 'right' as const,
      render: (inc: IncidentResponse) => (
        <span className="text-xs text-noc-text-muted">
          {new Date(inc.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      ),
    },
  ];

  const alarmColumns = [
    {
      key: 'alarm_id',
      header: 'Alarm ID',
      isMono: true,
      render: (alm: AlarmResponse) => (
        <span
          className="font-mono text-blue-400 font-semibold cursor-pointer hover:underline"
          onClick={() => navigate(`/alarms?id=${encodeURIComponent(alm.alarm_id)}`)}
        >
          {alm.alarm_id}
        </span>
      ),
    },
    {
      key: 'node_id',
      header: 'Node',
      isMono: true,
      render: (alm: AlarmResponse) => (
        <span className="text-xs text-noc-text-primary font-semibold">{alm.node_id}</span>
      ),
    },
    {
      key: 'severity',
      header: 'Severity',
      render: (alm: AlarmResponse) => <SeverityBadge severity={alm.severity} size="sm" />,
    },
    {
      key: 'status',
      header: 'Status',
      render: (alm: AlarmResponse) => (
        <StatusBadge status={alm.status.toLowerCase() as OperationalStatus} size="sm" />
      ),
    },
    {
      key: 'current_value',
      header: 'Observed / Thresh',
      isMono: true,
      render: (alm: AlarmResponse) => (
        <span className="text-xs text-noc-text-secondary">
          {alm.current_value.toFixed(1)} {alm.threshold !== null ? `/ ${alm.threshold.toFixed(1)}` : ''}
        </span>
      ),
    },
    {
      key: 'last_seen',
      header: 'Last Seen',
      isMono: true,
      align: 'right' as const,
      render: (alm: AlarmResponse) => (
        <span className="text-xs text-noc-text-muted">
          {new Date(alm.last_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Network Operations Center Overview"
        description="Unified real-time visibility across mobile network topology, active alarms, incident management, and SLA compliance."
        breadcrumbs={[{ label: 'NOC' }, { label: 'Overview' }]}
        actions={
          <div className="flex items-center gap-3">
            {lastRefreshed && (
              <span className="text-xs font-mono text-noc-text-muted">
                Updated: {new Date(lastRefreshed).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
            )}
            <button
              onClick={fetchOverviewData}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-noc-surface border border-noc-border hover:bg-noc-surface-hover text-xs font-medium text-noc-text-primary transition disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        }
      />

      {error && (
        <div className="mb-6">
          <ErrorState
            title="Backend Service Unreachable"
            message={error}
            onRetry={fetchOverviewData}
          />
        </div>
      )}

      {/* Primary KPI Cards Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div onClick={() => navigate('/network-map')} className="cursor-pointer">
          <MetricCard
            title="Total Network Nodes"
            value={topology ? topology.total_nodes : 0}
            unit="Nodes"
            subtitle={topology ? `${topology.tiers['CELL'] || 0} Cells, ${topology.tiers['SITE'] || 0} Sites` : 'Loading...'}
            status="healthy"
            icon={Network}
            loading={loading}
          />
        </div>

        <div onClick={() => navigate('/alarms?status=ACTIVE')} className="cursor-pointer">
          <MetricCard
            title="Active Alarms"
            value={activeAlarmsCount}
            unit="Active"
            subtitle={`${criticalAlarmsCount} Critical Severity`}
            status={criticalAlarmsCount > 0 ? 'critical' : activeAlarmsCount > 0 ? 'warning' : 'healthy'}
            icon={Bell}
            loading={loading}
          />
        </div>

        <div onClick={() => navigate('/incidents?status=OPEN')} className="cursor-pointer">
          <MetricCard
            title="Active Open Incidents"
            value={metrics ? metrics.open_incident_count : 0}
            unit="Incidents"
            subtitle={metrics ? `${metrics.total_incidents} Total Created` : 'Loading...'}
            status={metrics && metrics.open_incident_count > 0 ? 'critical' : 'healthy'}
            icon={AlertTriangle}
            loading={loading}
          />
        </div>

        <div onClick={() => navigate('/analytics')} className="cursor-pointer">
          <MetricCard
            title="SLA Breaches"
            value={totalSlaBreaches}
            unit="Violations"
            subtitle={metrics ? `Ack: ${metrics.ack_sla_breached_count} | Resolve: ${metrics.resolve_sla_breached_count}` : 'Ack / Resolve'}
            status={totalSlaBreaches > 0 ? 'critical' : 'healthy'}
            icon={ShieldAlert}
            loading={loading}
          />
        </div>
      </div>

      {/* Secondary Operational KPI Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div onClick={() => navigate('/alarms?severity=CRITICAL')} className="cursor-pointer">
          <MetricCard
            title="Critical Alarms"
            value={criticalAlarmsCount}
            unit="Critical"
            subtitle="Immediate dispatch priority"
            status={criticalAlarmsCount > 0 ? 'critical' : 'healthy'}
            icon={AlertOctagon}
            loading={loading}
          />
        </div>

        <div onClick={() => navigate('/incidents?status=ACKNOWLEDGED')} className="cursor-pointer">
          <MetricCard
            title="Acknowledged Incidents"
            value={acknowledgedCount}
            unit="In Triaging"
            subtitle="Assigned to operators"
            status="warning"
            icon={Activity}
            loading={loading}
          />
        </div>

        <div onClick={() => navigate('/analytics')} className="cursor-pointer">
          <MetricCard
            title="Mean Time To Acknowledge"
            value={formatDuration(metrics?.mtta_seconds ?? null)}
            unit="MTTA"
            subtitle="Acknowledge response time"
            status="healthy"
            icon={Clock}
            loading={loading}
          />
        </div>

        <div onClick={() => navigate('/analytics')} className="cursor-pointer">
          <MetricCard
            title="Mean Time To Resolve"
            value={formatDuration(metrics?.mttr_seconds ?? null)}
            unit="MTTR"
            subtitle={`${metrics?.incidents_by_status?.['RESOLVED'] ?? 0} Resolved Incidents`}
            status="healthy"
            icon={Clock}
            loading={loading}
          />
        </div>
      </div>

      {/* Network Health Summary Banner */}
      <div className="bg-noc-surface border border-noc-border rounded-lg p-4 mb-6">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-noc-border">
          <div className="flex items-center gap-2">
            <Radio className="w-4 h-4 text-blue-400" />
            <h3 className="text-sm font-semibold text-noc-text-primary">
              Authoritative Network Health Summary
            </h3>
          </div>
          <span className="text-[11px] font-mono text-noc-text-muted">
            Evaluated from Topology State & Recorded Telemetry
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div className="p-3 rounded bg-noc-base/60 border border-emerald-900/40">
            <div className="flex items-center justify-between text-xs font-semibold text-emerald-400">
              <span>Healthy</span>
              <CheckCircle2 className="w-4 h-4" />
            </div>
            <div className="mt-2 text-2xl font-mono font-bold text-noc-text-primary">
              {nodeHealthCounts.healthy}
            </div>
            <p className="text-[10px] text-noc-text-muted mt-0.5">Online & verified nominal telemetry</p>
          </div>

          <div className="p-3 rounded bg-noc-base/60 border border-amber-900/40">
            <div className="flex items-center justify-between text-xs font-semibold text-amber-400">
              <span>Degraded</span>
              <AlertTriangle className="w-4 h-4" />
            </div>
            <div className="mt-2 text-2xl font-mono font-bold text-noc-text-primary">
              {nodeHealthCounts.degraded}
            </div>
            <p className="text-[10px] text-noc-text-muted mt-0.5">Degraded status or low availability</p>
          </div>

          <div className="p-3 rounded bg-noc-base/60 border border-red-900/40">
            <div className="flex items-center justify-between text-xs font-semibold text-red-400">
              <span>Offline</span>
              <WifiOff className="w-4 h-4" />
            </div>
            <div className="mt-2 text-2xl font-mono font-bold text-noc-text-primary">
              {nodeHealthCounts.offline}
            </div>
            <p className="text-[10px] text-noc-text-muted mt-0.5">No carrier signal or transport cut</p>
          </div>

          <div className="p-3 rounded bg-noc-base/60 border border-slate-700/40">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-400">
              <span>Insufficient Telemetry</span>
              <Activity className="w-4 h-4" />
            </div>
            <div className="mt-2 text-2xl font-mono font-bold text-noc-text-primary">
              {nodeHealthCounts.insufficient_telemetry}
            </div>
            <p className="text-[10px] text-noc-text-muted mt-0.5">Simulation cycle not yet triggered</p>
          </div>

          <div className="p-3 rounded bg-noc-base/60 border border-slate-700/40">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-400">
              <span>Unknown</span>
              <HelpCircle className="w-4 h-4" />
            </div>
            <div className="mt-2 text-2xl font-mono font-bold text-noc-text-primary">
              {nodeHealthCounts.unknown}
            </div>
            <p className="text-[10px] text-noc-text-muted mt-0.5">Unregistered nodes</p>
          </div>
        </div>
      </div>

      {/* Distributions Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <BarChartDistribution
          title="Incident Severity Distribution"
          categories={severityDistribution}
          total={metrics?.total_incidents}
        />
        <BarChartDistribution
          title="Incident Status Distribution"
          categories={statusDistribution}
          total={metrics?.total_incidents}
        />
      </div>

      {/* Recent Incidents and Alarms Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Recent Incidents */}
        <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
          <div className="flex items-center justify-between pb-3 border-b border-noc-border mb-4">
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-blue-400" />
              <h3 className="text-sm font-semibold text-noc-text-primary">
                Recent Incident Queue
              </h3>
            </div>
            <button
              onClick={() => navigate('/incidents')}
              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium"
            >
              View all ({metrics?.total_incidents ?? 0})
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <DataTable
            columns={incidentColumns}
            data={recentIncidents}
            keyExtractor={(i) => i.incident_id}
            loading={loading}
            emptyMessage="No incidents currently logged in backend."
          />
        </div>

        {/* Recent Alarms */}
        <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
          <div className="flex items-center justify-between pb-3 border-b border-noc-border mb-4">
            <div className="flex items-center gap-2">
              <Bell className="w-4 h-4 text-blue-400" />
              <h3 className="text-sm font-semibold text-noc-text-primary">
                Recent Alarm Activity
              </h3>
            </div>
            <button
              onClick={() => navigate('/alarms')}
              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium"
            >
              View all ({activeAlarmsCount})
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <DataTable
            columns={alarmColumns}
            data={recentAlarms}
            keyExtractor={(a) => a.alarm_id}
            loading={loading}
            emptyMessage="No alarms recorded in alarm manager."
          />
        </div>
      </div>
    </div>
  );
};

export default OverviewPage;

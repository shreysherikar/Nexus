import React, { useCallback, useEffect, useState } from 'react';
import {
  BarChart3,
  Clock,
  PieChart,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { MetricCard } from '@/components/common/MetricCard';
import { ErrorState } from '@/components/common/ErrorState';
import { BarChartDistribution } from '@/components/common/BarChartDistribution';
import { apiClient } from '@/api/client';
import { IncidentMetricsResponse } from '@/types/api';
import { useWebSocketSubscription } from '@/websocket/useWebSocket';
import { WsEventType } from '@/types/websocket';

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return 'N/A';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const remSec = Math.round(seconds % 60);
  return remSec > 0 ? `${mins}m ${remSec}s` : `${mins}m`;
}

export const AnalyticsPage: React.FC = () => {
  const [metrics, setMetrics] = useState<IncidentMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getIncidentMetrics();
      setMetrics(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to query analytics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  // Live updates on incident transitions
  useWebSocketSubscription(WsEventType.INCIDENT_CREATED, () => {
    fetchMetrics();
  });
  useWebSocketSubscription(WsEventType.INCIDENT_ACKNOWLEDGED, () => {
    fetchMetrics();
  });
  useWebSocketSubscription(WsEventType.INCIDENT_RESOLVED, () => {
    fetchMetrics();
  });

  const total = metrics?.total_incidents || 0;
  const totalEvaluated = metrics?.total_incidents_evaluated || 0;
  const compliantCount = metrics?.compliant_incident_count || 0;
  const breachedCount = metrics?.breached_incident_count || 0;
  const ackBreaches = metrics?.ack_sla_breached_count || 0;
  const resolveBreaches = metrics?.resolve_sla_breached_count || 0;
  const compliancePct = metrics?.sla_compliance_pct ?? null;

  const complianceValue =
    compliancePct !== null && compliancePct !== undefined ? `${compliancePct}%` : 'N/A';

  const complianceSubtitle = metrics
    ? `${compliantCount} compliant / ${totalEvaluated} evaluated`
    : 'No data';

  const complianceStatus: 'healthy' | 'warning' | 'critical' | 'neutral' =
    compliancePct === null || compliancePct === undefined
      ? 'neutral'
      : breachedCount === 0
      ? 'healthy'
      : compliancePct >= 80
      ? 'warning'
      : 'critical';

  const severityDistribution = [
    {
      key: 'CRITICAL',
      label: 'Critical',
      value: metrics?.incidents_by_severity?.['CRITICAL'] ?? 0,
      color: '#ef4444',
    },
    {
      key: 'MAJOR',
      label: 'Major',
      value: metrics?.incidents_by_severity?.['MAJOR'] ?? 0,
      color: '#f97316',
    },
    {
      key: 'MINOR',
      label: 'Minor',
      value: metrics?.incidents_by_severity?.['MINOR'] ?? 0,
      color: '#eab308',
    },
    {
      key: 'WARNING',
      label: 'Warning',
      value: metrics?.incidents_by_severity?.['WARNING'] ?? 0,
      color: '#f59e0b',
    },
  ];

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

  const slaComplianceDistribution = [
    {
      key: 'COMPLIANT',
      label: 'Within All SLA Deadlines',
      value: compliantCount,
      color: '#10b981',
    },
    {
      key: 'BREACHED',
      label: 'Unique Breached Incidents',
      value: breachedCount,
      color: '#ef4444',
    },
    {
      key: 'ACK_BREACH',
      label: 'Acknowledgment SLA Breached',
      value: ackBreaches,
      color: '#f59e0b',
    },
    {
      key: 'RESOLVE_BREACH',
      label: 'Resolution SLA Breached',
      value: resolveBreaches,
      color: '#f87171',
    },
  ];

  return (
    <div>
      <PageHeader
        title="Incident Analytics & Operational SLA Tracking"
        description="Authoritative MTTA, MTTR, MTTD, severity distribution, and SLA compliance metrics computed by backend services."
        breadcrumbs={[{ label: 'NOC' }, { label: 'SLA & Analytics' }]}
        badge={
          metrics?.as_of ? (
            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-noc-base border border-noc-border text-noc-text-muted">
              As of: {new Date(metrics.as_of).toLocaleTimeString()} UTC
            </span>
          ) : undefined
        }
        actions={
          <button
            onClick={fetchMetrics}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-noc-surface border border-noc-border hover:bg-noc-surface-hover text-xs font-medium text-noc-text-primary transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        }
      />

      {error && (
        <div className="mb-6">
          <ErrorState
            title="Analytics Engine Query Failed"
            message={error}
            onRetry={fetchMetrics}
          />
        </div>
      )}

      {/* Analytics KPI Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard
          title="Overall SLA Compliance"
          value={complianceValue}
          subtitle={complianceSubtitle}
          status={complianceStatus}
          icon={ShieldCheck}
          loading={loading}
        />
        <MetricCard
          title="Mean Time To Acknowledge"
          value={formatDuration(metrics?.mtta_seconds ?? null)}
          unit="MTTA"
          subtitle={`Ack Breaches: ${ackBreaches}`}
          status="healthy"
          icon={TrendingUp}
          loading={loading}
        />
        <MetricCard
          title="Mean Time To Resolve"
          value={formatDuration(metrics?.mttr_seconds ?? null)}
          unit="MTTR"
          subtitle={`${metrics?.incidents_by_status?.['RESOLVED'] ?? 0} Resolved measured`}
          status="healthy"
          icon={Clock}
          loading={loading}
        />
        <MetricCard
          title="Mean Time To Detect"
          value={
            metrics?.mttd_seconds !== null && metrics?.mttd_seconds !== undefined
              ? formatDuration(metrics.mttd_seconds)
              : 'N/A'
          }
          unit="MTTD"
          subtitle="Detection pipeline latency"
          status="healthy"
          icon={BarChart3}
          loading={loading}
        />
      </div>

      {/* Distribution Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <BarChartDistribution
          title="Incident Severity Distribution"
          categories={severityDistribution}
          total={total}
        />
        <BarChartDistribution
          title="Incident Status Distribution"
          categories={statusDistribution}
          total={total}
        />
        <BarChartDistribution
          title="SLA Compliance Breakdown"
          categories={slaComplianceDistribution}
          total={Math.max(totalEvaluated, compliantCount + breachedCount)}
        />
      </div>

      {/* Measured Operational Detail Box */}
      <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
        <div className="flex items-center justify-between pb-3 mb-4 border-b border-noc-border">
          <div className="flex items-center gap-2">
            <PieChart className="w-4 h-4 text-blue-400" />
            <h3 className="text-sm font-semibold text-noc-text-primary">
              Authoritative Metrics Detail
            </h3>
          </div>
          <span className="text-xs font-mono text-noc-text-muted">
            GET /api/v1/incidents/metrics
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 text-xs font-mono">
          <div className="p-3 rounded bg-noc-base border border-noc-border">
            <div className="text-noc-text-muted">Total Recorded Incidents</div>
            <div className="text-xl font-bold text-noc-text-primary mt-1">{total}</div>
          </div>
          <div className="p-3 rounded bg-noc-base border border-noc-border">
            <div className="text-noc-text-muted">SLA Evaluated Incidents</div>
            <div className="text-xl font-bold text-blue-400 mt-1">{totalEvaluated}</div>
          </div>
          <div className="p-3 rounded bg-noc-base border border-noc-border">
            <div className="text-noc-text-muted">Compliant Incidents</div>
            <div className="text-xl font-bold text-emerald-400 mt-1">{compliantCount}</div>
          </div>
          <div className="p-3 rounded bg-noc-base border border-noc-border">
            <div className="text-noc-text-muted">Acknowledgment Breaches</div>
            <div className="text-xl font-bold text-amber-400 mt-1">{ackBreaches}</div>
          </div>
          <div className="p-3 rounded bg-noc-base border border-noc-border">
            <div className="text-noc-text-muted">Resolution Breaches</div>
            <div className="text-xl font-bold text-rose-400 mt-1">{resolveBreaches}</div>
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-noc-border text-xs text-noc-text-muted">
          NOC SLA targets are derived from backend severity policy models. Metrics represent actual measured operations and are never synthesized or extrapolated.
        </div>
      </div>
    </div>
  );
};

export default AnalyticsPage;

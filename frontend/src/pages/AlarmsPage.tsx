import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Bell,
  Filter,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { DataTable } from '@/components/common/DataTable';
import { SeverityBadge } from '@/components/common/SeverityBadge';
import { OperationalStatus, StatusBadge } from '@/components/common/StatusBadge';
import { ErrorState } from '@/components/common/ErrorState';
import { apiClient } from '@/api/client';
import { AlarmResponse } from '@/types/api';
import { useWebSocketSubscription } from '@/websocket/useWebSocket';
import { AlarmCreatedPayload, AlarmClearedPayload, AlarmUpdatedPayload, WsEventType } from '@/types/websocket';

export const AlarmsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  const [alarms, setAlarms] = useState<AlarmResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination & Filtering
  const [page, setPage] = useState(1);
  const limit = 15;
  const severityFilter = searchParams.get('severity') || '';
  const statusFilter = searchParams.get('status') || '';
  const initialId = searchParams.get('id') || '';
  const [searchNode, setSearchNode] = useState(searchParams.get('node_id') || '');
  const [searchRule, setSearchRule] = useState('');

  // Selected Alarm Drawer
  const [selectedAlarm, setSelectedAlarm] = useState<AlarmResponse | null>(null);

  const fetchAlarms = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * limit;
      const res = await apiClient.getAlarms({
        node_id: searchNode || undefined,
        severity: severityFilter || undefined,
        status: statusFilter || undefined,
        limit,
        offset,
      });
      setAlarms(res.items);
      setTotal(res.total);

      // If initialId was passed in URL query param, open it
      if (initialId && !selectedAlarm) {
        const found = res.items.find((a) => a.alarm_id === initialId);
        if (found) {
          setSelectedAlarm(found);
        } else {
          apiClient.getAlarmById(initialId).then((a) => setSelectedAlarm(a)).catch(() => {});
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to query alarms');
    } finally {
      setLoading(false);
    }
  }, [page, limit, searchNode, severityFilter, statusFilter, initialId, selectedAlarm]);

  useEffect(() => {
    fetchAlarms();
  }, [fetchAlarms]);

  // WebSocket subscriptions for live alarm state changes
  useWebSocketSubscription<AlarmCreatedPayload>(WsEventType.ALARM_CREATED, () => {
    fetchAlarms();
  });
  useWebSocketSubscription<AlarmUpdatedPayload>(WsEventType.ALARM_UPDATED, () => {
    fetchAlarms();
  });
  useWebSocketSubscription<AlarmClearedPayload>(WsEventType.ALARM_CLEARED, () => {
    fetchAlarms();
  });

  const handleSeverityChange = (newSev: string) => {
    const nextParams = new URLSearchParams(searchParams);
    if (newSev) {
      nextParams.set('severity', newSev);
    } else {
      nextParams.delete('severity');
    }
    setSearchParams(nextParams);
    setPage(1);
  };

  const handleStatusChange = (newStatus: string) => {
    const nextParams = new URLSearchParams(searchParams);
    if (newStatus) {
      nextParams.set('status', newStatus);
    } else {
      nextParams.delete('status');
    }
    setSearchParams(nextParams);
    setPage(1);
  };

  // Client-side rule search filtering over current page
  const displayedAlarms = useMemo(() => {
    if (!searchRule.trim()) return alarms;
    return alarms.filter((a) =>
      a.rule_id.toLowerCase().includes(searchRule.toLowerCase().trim())
    );
  }, [alarms, searchRule]);

  const totalPages = Math.max(1, Math.ceil(total / limit));

  const columns = [
    {
      key: 'alarm_id',
      header: 'Alarm ID',
      isMono: true,
      render: (a: AlarmResponse) => (
        <span
          className="font-mono text-blue-400 font-semibold cursor-pointer hover:underline"
          onClick={() => setSelectedAlarm(a)}
        >
          {a.alarm_id}
        </span>
      ),
    },
    {
      key: 'node_id',
      header: 'Node ID',
      isMono: true,
      render: (a: AlarmResponse) => (
        <span className="font-semibold text-noc-text-primary">{a.node_id}</span>
      ),
    },
    {
      key: 'metric_name',
      header: 'Metric',
      isMono: true,
      render: (a: AlarmResponse) => (
        <span className="text-xs text-noc-text-secondary">{a.metric_name}</span>
      ),
    },
    {
      key: 'rule_id',
      header: 'Detector Rule',
      isMono: true,
      render: (a: AlarmResponse) => (
        <span className="text-[11px] text-noc-text-muted">{a.rule_id}</span>
      ),
    },
    {
      key: 'severity',
      header: 'Severity',
      render: (a: AlarmResponse) => <SeverityBadge severity={a.severity} size="sm" />,
    },
    {
      key: 'status',
      header: 'Status',
      render: (a: AlarmResponse) => (
        <StatusBadge status={a.status.toLowerCase() as OperationalStatus} size="sm" />
      ),
    },
    {
      key: 'current_value',
      header: 'Observed / Thresh',
      isMono: true,
      render: (a: AlarmResponse) => (
        <span className="text-xs font-mono text-noc-text-primary">
          {a.current_value.toFixed(1)} {a.threshold !== null ? `/ ${a.threshold.toFixed(1)}` : ''}
        </span>
      ),
    },
    {
      key: 'observation_count',
      header: 'Obs Count',
      isMono: true,
      render: (a: AlarmResponse) => (
        <span className="text-xs font-mono text-noc-text-secondary">{a.observation_count}</span>
      ),
    },
    {
      key: 'last_seen',
      header: 'Last Seen',
      isMono: true,
      align: 'right' as const,
      render: (a: AlarmResponse) => (
        <span className="text-xs text-noc-text-muted">
          {new Date(a.last_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Network Alarms Inventory"
        description="Threshold and statistical anomaly detection alarms emitted by the NEXUS detection engine."
        breadcrumbs={[{ label: 'NOC' }, { label: 'Alarms' }]}
        actions={
          <button
            onClick={fetchAlarms}
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
          <ErrorState title="Alarm Query Failed" message={error} onRetry={fetchAlarms} />
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="bg-noc-surface border border-noc-border rounded-lg p-4 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {/* Node Search */}
          <div className="relative min-w-[150px]">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-noc-text-muted" />
            <input
              type="text"
              placeholder="Filter by Node ID..."
              value={searchNode}
              onChange={(e) => {
                setSearchNode(e.target.value);
                setPage(1);
              }}
              className="w-full pl-8 pr-3 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-primary placeholder:text-noc-text-muted text-xs focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Rule Search */}
          <div className="relative min-w-[150px]">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-noc-text-muted" />
            <input
              type="text"
              placeholder="Filter by Rule ID..."
              value={searchRule}
              onChange={(e) => setSearchRule(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-primary placeholder:text-noc-text-muted text-xs focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Severity Filter */}
          <div className="flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-noc-text-muted" />
            <select
              value={severityFilter}
              onChange={(e) => handleSeverityChange(e.target.value)}
              className="px-2 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-secondary text-xs focus:outline-none focus:border-blue-500"
            >
              <option value="">All Severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="MAJOR">Major</option>
              <option value="WARNING">Warning</option>
            </select>
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-1.5">
            <select
              value={statusFilter}
              onChange={(e) => handleStatusChange(e.target.value)}
              className="px-2 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-secondary text-xs focus:outline-none focus:border-blue-500"
            >
              <option value="">All Statuses</option>
              <option value="ACTIVE">Active Alarms</option>
              <option value="CLEARED">Cleared Alarms</option>
            </select>
          </div>
        </div>

        <div className="text-xs font-mono text-noc-text-muted">
          Total Matching Alarms: <strong className="text-noc-text-primary">{total}</strong>
        </div>
      </div>

      {/* Alarms Data Table */}
      <div className="bg-noc-surface border border-noc-border rounded-lg p-5 mb-6">
        <DataTable
          columns={columns}
          data={displayedAlarms}
          keyExtractor={(a) => a.alarm_id}
          loading={loading}
          emptyMessage="No alarms match current filter criteria."
        />

        {/* Pagination Controls */}
        <div className="flex items-center justify-between pt-4 mt-4 border-t border-noc-border text-xs">
          <span className="text-noc-text-muted font-mono">
            Page {page} of {totalPages} ({total} alarms)
          </span>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-3 py-1 rounded bg-noc-base border border-noc-border text-noc-text-secondary hover:text-noc-text-primary disabled:opacity-40 transition"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-1 rounded bg-noc-base border border-noc-border text-noc-text-secondary hover:text-noc-text-primary disabled:opacity-40 transition"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* Alarm Detail Drawer Modal */}
      {selectedAlarm && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-lg bg-noc-surface border-l border-noc-border h-full overflow-y-auto p-6 shadow-2xl flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-4 border-b border-noc-border mb-5">
                <div className="flex items-center gap-2">
                  <Bell className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-semibold text-noc-text-primary">Alarm Record Details</h3>
                </div>
                <button
                  onClick={() => setSelectedAlarm(null)}
                  className="p-1 rounded hover:bg-noc-base text-noc-text-muted hover:text-noc-text-primary transition"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-4 text-xs font-mono">
                <div className="p-3.5 rounded bg-noc-base border border-noc-border">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-sm text-noc-text-primary">
                      {selectedAlarm.alarm_id}
                    </span>
                    <SeverityBadge severity={selectedAlarm.severity} size="sm" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-noc-text-muted">Status:</span>
                    <StatusBadge
                      status={selectedAlarm.status.toLowerCase() as OperationalStatus}
                      size="sm"
                    />
                  </div>
                </div>

                <div className="space-y-2 p-3.5 rounded bg-noc-base border border-noc-border">
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Target Node:</span>
                    <span className="font-bold text-noc-text-primary">{selectedAlarm.node_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Monitored Metric:</span>
                    <span className="text-noc-text-primary">{selectedAlarm.metric_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Rule Identifier:</span>
                    <span className="text-noc-text-primary">{selectedAlarm.rule_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Detection Source:</span>
                    <span className="text-noc-text-primary">{selectedAlarm.source}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Current Value:</span>
                    <span className="font-bold text-amber-400">
                      {selectedAlarm.current_value.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Threshold / Baseline:</span>
                    <span className="text-noc-text-primary">
                      {selectedAlarm.threshold !== null ? selectedAlarm.threshold.toFixed(2) : 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Observation Count:</span>
                    <span className="text-noc-text-primary">{selectedAlarm.observation_count} cycles</span>
                  </div>
                </div>

                {/* Timestamps */}
                <div className="space-y-2 p-3.5 rounded bg-noc-base border border-noc-border">
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">First Detected:</span>
                    <span className="text-noc-text-secondary">
                      {new Date(selectedAlarm.first_seen).toISOString().replace('T', ' ').substring(0, 19)} UTC
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Latest Evaluation:</span>
                    <span className="text-noc-text-secondary">
                      {new Date(selectedAlarm.last_seen).toISOString().replace('T', ' ').substring(0, 19)} UTC
                    </span>
                  </div>
                  {selectedAlarm.cleared_at && (
                    <div className="flex justify-between">
                      <span className="text-noc-text-muted">Recovery Cleared:</span>
                      <span className="text-emerald-400">
                        {new Date(selectedAlarm.cleared_at).toISOString().replace('T', ' ').substring(0, 19)} UTC
                      </span>
                    </div>
                  )}
                </div>

                {/* Condition Description */}
                {selectedAlarm.description && (
                  <div className="p-3.5 rounded bg-noc-base border border-noc-border">
                    <span className="text-noc-text-muted block mb-1">Description:</span>
                    <p className="text-noc-text-secondary font-sans text-xs">
                      {selectedAlarm.description}
                    </p>
                  </div>
                )}

                {/* Diagnostic Evidence */}
                {Object.keys(selectedAlarm.evidence || {}).length > 0 && (
                  <div className="p-3.5 rounded bg-noc-base border border-noc-border">
                    <span className="text-noc-text-muted block mb-2">Diagnostic Evidence:</span>
                    <pre className="text-[11px] text-noc-text-muted bg-noc-surface p-2 rounded overflow-x-auto">
                      {JSON.stringify(selectedAlarm.evidence, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>

            <div className="pt-4 border-t border-noc-border text-xs text-noc-text-muted">
              Note: Alarms are managed authoritatively by the detection engine. Lifecycle acknowledgment and resolution are executed via Incidents.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AlarmsPage;

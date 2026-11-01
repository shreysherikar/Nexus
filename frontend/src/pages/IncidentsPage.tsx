import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  CheckCircle,
  Filter,
  RefreshCw,
  Server,
  UserCheck,
  X,
} from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { DataTable } from '@/components/common/DataTable';
import { SeverityBadge } from '@/components/common/SeverityBadge';
import { OperationalStatus, StatusBadge } from '@/components/common/StatusBadge';
import { ErrorState } from '@/components/common/ErrorState';
import { apiClient } from '@/api/client';
import { IncidentResponse, TimelineEventResponse } from '@/types/api';
import { useWebSocketSubscription } from '@/websocket/useWebSocket';
import { IncidentAcknowledgedPayload, IncidentCreatedPayload, IncidentResolvedPayload, WsEventType } from '@/types/websocket';

export const IncidentsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  const [incidents, setIncidents] = useState<IncidentResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const limit = 10;
  const statusFilter = searchParams.get('status') || '';
  const severityFilter = searchParams.get('severity') || '';
  const initialId = searchParams.get('id') || '';

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Selected incident for drawer/detail modal
  const [selectedIncident, setSelectedIncident] = useState<IncidentResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineEventResponse[]>([]);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Lifecycle Action State & Confirmation
  const [actionInProgress, setActionInProgress] = useState(false);
  const [confirmModal, setConfirmModal] = useState<'ACKNOWLEDGE' | 'RESOLVE' | null>(null);
  const [actorName, setActorName] = useState('NOC_OPERATOR');
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);

  const fetchIncidents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * limit;
      const res = await apiClient.getIncidents({
        limit,
        offset,
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
      });
      setIncidents(res.items);
      setTotal(res.total);

      // Handle query param opening specific incident
      if (initialId && !selectedIncident) {
        const found = res.items.find((i) => i.incident_id === initialId);
        if (found) {
          setSelectedIncident(found);
          loadTimeline(found.incident_id);
        } else {
          apiClient.getIncidentById(initialId).then((inc) => {
            setSelectedIncident(inc);
            loadTimeline(inc.incident_id);
          }).catch(() => {});
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query incidents';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [page, limit, statusFilter, severityFilter, initialId, selectedIncident]);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  // WebSocket subscriptions for live incident lifecycle transitions
  useWebSocketSubscription<IncidentCreatedPayload>(WsEventType.INCIDENT_CREATED, () => {
    fetchIncidents();
  });
  useWebSocketSubscription<IncidentAcknowledgedPayload>(WsEventType.INCIDENT_ACKNOWLEDGED, (payload) => {
    fetchIncidents();
    if (selectedIncident && selectedIncident.incident_id === payload.incident_id) {
      apiClient.getIncidentById(payload.incident_id).then((updated) => {
        setSelectedIncident(updated);
        loadTimeline(updated.incident_id);
      }).catch(() => {});
    }
  });
  useWebSocketSubscription<IncidentResolvedPayload>(WsEventType.INCIDENT_RESOLVED, (payload) => {
    fetchIncidents();
    if (selectedIncident && selectedIncident.incident_id === payload.incident_id) {
      apiClient.getIncidentById(payload.incident_id).then((updated) => {
        setSelectedIncident(updated);
        loadTimeline(updated.incident_id);
      }).catch(() => {});
    }
  });

  const loadTimeline = async (incId: string) => {
    setLoadingTimeline(true);
    try {
      const events = await apiClient.getIncidentTimeline(incId);
      setTimeline(events);
    } catch {
      setTimeline([]);
    } finally {
      setLoadingTimeline(false);
    }
  };

  const handleSelectIncident = (inc: IncidentResponse) => {
    setSelectedIncident(inc);
    setActionError(null);
    setValidationError(null);
    loadTimeline(inc.incident_id);
  };

  const executeAcknowledge = async () => {
    if (!selectedIncident) return;
    if (!actorName.trim()) {
      setValidationError('Actor identity is required');
      return;
    }

    setActionInProgress(true);
    setActionError(null);
    setValidationError(null);
    try {
      const updated = await apiClient.acknowledgeIncident(selectedIncident.incident_id, {
        actor: actorName.trim(),
      });
      setSelectedIncident(updated);
      setConfirmModal(null);
      await fetchIncidents();
      await loadTimeline(updated.incident_id);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to acknowledge incident');
    } finally {
      setActionInProgress(false);
    }
  };

  const executeResolve = async () => {
    if (!selectedIncident) return;
    if (!actorName.trim()) {
      setValidationError('Actor identity is required');
      return;
    }
    if (!resolutionNotes.trim()) {
      setValidationError('Resolution notes are mandatory to confirm RCA findings and corrective action');
      return;
    }

    setActionInProgress(true);
    setActionError(null);
    setValidationError(null);
    try {
      const updated = await apiClient.resolveIncident(selectedIncident.incident_id, {
        actor: actorName.trim(),
        notes: resolutionNotes.trim(),
      });
      setSelectedIncident(updated);
      setConfirmModal(null);
      setResolutionNotes('');
      await fetchIncidents();
      await loadTimeline(updated.incident_id);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to resolve incident');
    } finally {
      setActionInProgress(false);
    }
  };

  const handleStatusFilterChange = (newStatus: string) => {
    const nextParams = new URLSearchParams(searchParams);
    if (newStatus) {
      nextParams.set('status', newStatus);
    } else {
      nextParams.delete('status');
    }
    setSearchParams(nextParams);
    setPage(1);
  };

  const handleSeverityFilterChange = (newSev: string) => {
    const nextParams = new URLSearchParams(searchParams);
    if (newSev) {
      nextParams.set('severity', newSev);
    } else {
      nextParams.delete('severity');
    }
    setSearchParams(nextParams);
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(total / limit));

  const columns = [
    {
      key: 'incident_id',
      header: 'Incident ID',
      isMono: true,
      render: (inc: IncidentResponse) => (
        <span
          className="font-mono text-blue-400 font-semibold cursor-pointer hover:underline"
          onClick={() => handleSelectIncident(inc)}
        >
          {inc.incident_id}
        </span>
      ),
    },
    {
      key: 'severity',
      header: 'Severity / Prio',
      render: (inc: IncidentResponse) => (
        <div className="flex items-center gap-1.5">
          <SeverityBadge severity={inc.severity} size="sm" />
          <span className="text-[11px] font-mono text-noc-text-muted">{inc.priority}</span>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Lifecycle',
      render: (inc: IncidentResponse) => (
        <StatusBadge status={inc.status.toLowerCase() as OperationalStatus} size="sm" />
      ),
    },
    {
      key: 'title',
      header: 'Summary & Impacted Nodes',
      render: (inc: IncidentResponse) => (
        <div className="max-w-md">
          <div className="text-noc-text-primary font-medium truncate" title={inc.title}>
            {inc.title}
          </div>
          <div className="text-[11px] font-mono text-noc-text-muted mt-0.5 truncate">
            Nodes: {inc.affected_node_ids.join(', ') || 'N/A'}
          </div>
        </div>
      ),
    },
    {
      key: 'rca',
      header: 'RCA Hypothesis',
      isMono: true,
      render: (inc: IncidentResponse) => (
        <div className="text-xs">
          <span className="text-noc-text-secondary font-medium">
            {inc.suspected_cause_type || 'DIAGNOSING'}
          </span>
          {inc.rca_confidence_score !== null && inc.rca_confidence_score !== undefined && (
            <span className="text-emerald-400 text-[11px] ml-1">
              ({Math.round(inc.rca_confidence_score * 100)}%)
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'sla',
      header: 'SLA Status',
      isMono: true,
      render: (inc: IncidentResponse) => {
        const sla = inc.sla_status;
        if (!sla) {
          return <span className="text-[11px] font-mono text-noc-text-muted">N/A</span>;
        }
        const isBreached = sla.ack_breached || sla.resolve_breached;
        return (
          <span
            className={`px-1.5 py-0.5 rounded text-[11px] border font-mono ${
              isBreached
                ? 'bg-rose-950/70 border-rose-700/60 text-rose-300'
                : 'bg-emerald-950/70 border-emerald-700/60 text-emerald-300'
            }`}
          >
            {isBreached ? 'BREACHED' : 'IN SLA'}
          </span>
        );
      },
    },
    {
      key: 'actions',
      header: 'Action',
      align: 'right' as const,
      render: (inc: IncidentResponse) => (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleSelectIncident(inc);
          }}
          className="px-2.5 py-1 bg-noc-base hover:bg-noc-surface border border-noc-border rounded text-xs text-noc-text-secondary hover:text-noc-text-primary transition flex items-center gap-1 font-mono"
        >
          Inspect
        </button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Incident Operations & Lifecycle Workspace"
        description="Authoritative incident management, automated RCA evidence inspection, and operational SLA lifecycle tracking."
        breadcrumbs={[{ label: 'NOC' }, { label: 'Incidents' }]}
        actions={
          <button
            onClick={fetchIncidents}
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
          <ErrorState title="Incident Query Failed" message={error} onRetry={fetchIncidents} />
        </div>
      )}

      {/* Filter and Status Controls */}
      <div className="bg-noc-surface border border-noc-border rounded-lg p-4 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-noc-text-muted" />
            <select
              value={statusFilter}
              onChange={(e) => handleStatusFilterChange(e.target.value)}
              className="px-2.5 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-secondary text-xs focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="">All Statuses</option>
              <option value="OPEN">Open Incidents</option>
              <option value="ACKNOWLEDGED">Acknowledged WIP</option>
              <option value="RESOLVED">Resolved</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5">
            <select
              value={severityFilter}
              onChange={(e) => handleSeverityFilterChange(e.target.value)}
              className="px-2.5 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-secondary text-xs focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="">All Severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="MAJOR">Major</option>
              <option value="MINOR">Minor</option>
              <option value="WARNING">Warning</option>
            </select>
          </div>
        </div>

        <div className="text-xs font-mono text-noc-text-muted">
          Total Matching Incidents: <strong className="text-noc-text-primary">{total}</strong>
        </div>
      </div>

      {/* Incidents Table */}
      <div className="bg-noc-surface border border-noc-border rounded-lg p-5 mb-6">
        <DataTable
          columns={columns}
          data={incidents}
          keyExtractor={(i) => i.incident_id}
          loading={loading}
          emptyMessage="No incidents match the selected status or severity filters."
        />

        {/* Pagination */}
        <div className="flex items-center justify-between pt-4 mt-4 border-t border-noc-border text-xs">
          <span className="text-noc-text-muted font-mono">
            Page {page} of {totalPages} ({total} incidents)
          </span>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-3 py-1 rounded bg-noc-base border border-noc-border text-noc-text-secondary hover:text-noc-text-primary disabled:opacity-40 transition font-mono"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-1 rounded bg-noc-base border border-noc-border text-noc-text-secondary hover:text-noc-text-primary disabled:opacity-40 transition font-mono"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* Incident Detail Drawer Modal */}
      {selectedIncident && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-xl bg-noc-surface border-l border-noc-border h-full overflow-y-auto p-6 shadow-2xl flex flex-col justify-between">
            <div>
              {/* Drawer Header */}
              <div className="flex items-center justify-between pb-4 border-b border-noc-border mb-5">
                <div className="flex items-center gap-2">
                  <Server className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-semibold text-noc-text-primary">
                    Incident Context & Diagnostics
                  </h3>
                </div>
                <button
                  onClick={() => setSelectedIncident(null)}
                  className="p-1 rounded hover:bg-noc-base text-noc-text-muted hover:text-noc-text-primary transition"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {actionError && (
                <div className="p-3 mb-4 rounded bg-rose-950/60 border border-rose-800 text-rose-300 text-xs">
                  {actionError}
                </div>
              )}

              {/* Identity & Status */}
              <div className="space-y-4 text-xs font-mono">
                <div className="p-3.5 rounded bg-noc-base border border-noc-border">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-sm text-blue-400">
                      {selectedIncident.incident_id}
                    </span>
                    <div className="flex items-center gap-2">
                      <SeverityBadge severity={selectedIncident.severity} size="sm" />
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-noc-surface border border-noc-border text-noc-text-secondary">
                        {selectedIncident.priority}
                      </span>
                    </div>
                  </div>
                  <h4 className="font-sans font-semibold text-sm text-noc-text-primary mb-1">
                    {selectedIncident.title}
                  </h4>
                  <p className="font-sans text-xs text-noc-text-secondary leading-relaxed">
                    {selectedIncident.description}
                  </p>
                </div>

                {/* Impacted Entities & Alarms */}
                <div className="p-3.5 rounded bg-noc-base border border-noc-border space-y-2">
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Lifecycle Status:</span>
                    <StatusBadge
                      status={selectedIncident.status.toLowerCase() as OperationalStatus}
                      size="sm"
                    />
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Impacted Nodes:</span>
                    <span className="text-noc-text-primary">
                      {selectedIncident.affected_node_ids.join(', ') || 'None reported'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Correlated Alarms:</span>
                    <span className="text-noc-text-primary">{selectedIncident.alarm_ids.length} alarms</span>
                  </div>
                  {selectedIncident.alarm_ids.length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {selectedIncident.alarm_ids.map((aid) => (
                        <span key={aid} className="text-[10px] px-1.5 py-0.5 rounded bg-noc-surface border border-noc-border text-noc-text-muted">
                          {aid}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* SLA Targets & Deadlines */}
                <div className="p-3.5 rounded bg-noc-base border border-noc-border space-y-2">
                  <div className="flex justify-between font-bold text-noc-text-primary pb-1 border-b border-noc-border">
                    <span>SLA Deadline Compliance</span>
                    <span
                      className={
                        selectedIncident.sla_status?.ack_breached ||
                        selectedIncident.sla_status?.resolve_breached
                          ? 'text-rose-400'
                          : 'text-emerald-400'
                      }
                    >
                      {selectedIncident.sla_status?.ack_breached ||
                      selectedIncident.sla_status?.resolve_breached
                        ? 'SLA BREACHED'
                        : 'SLA COMPLIANT'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Created:</span>
                    <span className="text-noc-text-secondary">
                      {new Date(selectedIncident.created_at).toISOString().replace('T', ' ').substring(0, 19)} UTC
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Ack Deadline:</span>
                    <span className="text-noc-text-secondary">
                      {new Date(selectedIncident.ack_deadline).toISOString().replace('T', ' ').substring(0, 19)} UTC
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-noc-text-muted">Resolve Deadline:</span>
                    <span className="text-noc-text-secondary">
                      {new Date(selectedIncident.resolve_deadline).toISOString().replace('T', ' ').substring(0, 19)} UTC
                    </span>
                  </div>
                  {selectedIncident.acknowledged_at && (
                    <div className="flex justify-between text-amber-300">
                      <span>Acknowledged By:</span>
                      <span>
                        {selectedIncident.acknowledged_by} (
                        {new Date(selectedIncident.acknowledged_at).toLocaleTimeString()})
                      </span>
                    </div>
                  )}
                  {selectedIncident.resolved_at && (
                    <div className="flex justify-between text-emerald-300">
                      <span>Resolved By:</span>
                      <span>
                        {selectedIncident.resolved_by} (
                        {new Date(selectedIncident.resolved_at).toLocaleTimeString()})
                      </span>
                    </div>
                  )}
                </div>

                {/* RCA Diagnostics */}
                <div className="p-3.5 rounded bg-noc-base border border-noc-border space-y-2">
                  <span className="font-bold text-noc-text-primary block pb-1 border-b border-noc-border">
                    Root Cause Analysis (RCA)
                  </span>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-noc-text-muted">Suspected Cause: </span>
                      <span className="text-amber-300 font-bold">
                        {selectedIncident.suspected_cause_type || 'UNCONFIRMED'}
                      </span>
                    </div>
                    <div>
                      <span className="text-noc-text-muted">Suspected Target: </span>
                      <span className="text-blue-300 font-bold">
                        {selectedIncident.suspected_target_id || 'UNKNOWN'}
                      </span>
                    </div>
                    <div>
                      <span className="text-noc-text-muted">Confidence: </span>
                      <span className="text-emerald-300 font-bold">
                        {selectedIncident.rca_confidence_score !== null &&
                        selectedIncident.rca_confidence_score !== undefined
                          ? `${Math.round(selectedIncident.rca_confidence_score * 100)}%`
                          : 'N/A'}
                      </span>
                    </div>
                  </div>

                  {selectedIncident.rca_hypotheses.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-noc-border">
                      <span className="text-[11px] text-noc-text-muted block mb-1">
                        Engine Explanation:
                      </span>
                      <p className="text-xs text-noc-text-secondary leading-relaxed font-sans">
                        {String(selectedIncident.rca_hypotheses[0]?.explanation || 'No explanation recorded')}
                      </p>
                    </div>
                  )}
                </div>

                {/* Audit Timeline */}
                <div>
                  <span className="font-bold text-noc-text-primary block mb-2">
                    Lifecycle Audit Timeline
                  </span>
                  {loadingTimeline ? (
                    <div className="text-center py-4 text-noc-text-muted">Loading audit log...</div>
                  ) : timeline.length === 0 ? (
                    <div className="p-3 bg-noc-base rounded border border-noc-border text-center text-noc-text-muted">
                      No audit timeline events found.
                    </div>
                  ) : (
                    <div className="space-y-1.5 max-h-48 overflow-y-auto">
                      {timeline.map((evt) => (
                        <div
                          key={evt.event_id}
                          className="p-2 rounded bg-noc-base border border-noc-border flex items-start justify-between gap-3 text-[11px]"
                        >
                          <div>
                            <span className="text-blue-400 font-semibold">{evt.event_type}</span>
                            <span className="text-noc-text-muted mx-1">by</span>
                            <span className="text-noc-text-secondary font-medium">{evt.actor}</span>
                            {evt.details && Object.keys(evt.details).length > 0 && (
                              <div className="text-[10px] text-noc-text-muted mt-0.5">
                                {JSON.stringify(evt.details)}
                              </div>
                            )}
                          </div>
                          <span className="text-noc-text-muted shrink-0">
                            {new Date(evt.timestamp).toLocaleTimeString()}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Lifecycle Mutation Actions */}
            <div className="pt-4 mt-4 border-t border-noc-border bg-noc-base/40 flex items-center justify-between">
              <span className="text-xs font-mono text-noc-text-muted">
                Group: {selectedIncident.correlation_group_id}
              </span>

              <div className="flex items-center gap-2">
                {selectedIncident.status === 'OPEN' && (
                  <button
                    onClick={() => {
                      setValidationError(null);
                      setConfirmModal('ACKNOWLEDGE');
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white font-medium text-xs transition"
                  >
                    <UserCheck className="w-3.5 h-3.5" />
                    Acknowledge
                  </button>
                )}

                {selectedIncident.status !== 'RESOLVED' && (
                  <button
                    onClick={() => {
                      setValidationError(null);
                      setConfirmModal('RESOLVE');
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs transition"
                  >
                    <CheckCircle className="w-3.5 h-3.5" />
                    Resolve Incident
                  </button>
                )}

                <button
                  onClick={() => setSelectedIncident(null)}
                  className="px-3 py-1.5 rounded bg-noc-surface border border-noc-border text-xs text-noc-text-secondary hover:text-noc-text-primary transition"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal for Lifecycle Mutations */}
      {confirmModal && selectedIncident && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fade-in">
          <div className="w-full max-w-md bg-noc-surface border border-noc-border rounded-lg p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-noc-border">
              <h3 className="text-sm font-semibold text-noc-text-primary">
                {confirmModal === 'ACKNOWLEDGE' ? 'Confirm Incident Acknowledgment' : 'Confirm Incident Resolution'}
              </h3>
              <button
                onClick={() => setConfirmModal(null)}
                className="p-1 rounded text-noc-text-muted hover:text-noc-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-noc-text-secondary leading-relaxed">
              {confirmModal === 'ACKNOWLEDGE'
                ? `You are about to acknowledge incident ${selectedIncident.incident_id}. This assigns active triage ownership to the specified operator and halts the acknowledgment SLA timer.`
                : `You are about to mark incident ${selectedIncident.incident_id} as RESOLVED. Please document the root cause resolution notes below.`}
            </p>

            {validationError && (
              <div className="p-2.5 rounded bg-rose-950/60 border border-rose-800 text-rose-300 text-xs">
                {validationError}
              </div>
            )}

            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-noc-text-muted mb-1 font-mono">Operator Identity (Actor):</label>
                <input
                  type="text"
                  value={actorName}
                  onChange={(e) => setActorName(e.target.value)}
                  placeholder="e.g. NOC_OPERATOR_01"
                  className="w-full px-3 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-primary font-mono focus:outline-none focus:border-blue-500"
                />
              </div>

              {confirmModal === 'RESOLVE' && (
                <div>
                  <label className="block text-noc-text-muted mb-1 font-mono">Resolution Notes & Findings (Required):</label>
                  <textarea
                    rows={3}
                    value={resolutionNotes}
                    onChange={(e) => setResolutionNotes(e.target.value)}
                    placeholder="Describe corrective actions taken (e.g. Fiber rerouted, power restored)..."
                    className="w-full px-3 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-primary font-mono focus:outline-none focus:border-blue-500"
                  />
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-noc-border">
              <button
                onClick={() => setConfirmModal(null)}
                disabled={actionInProgress}
                className="px-3 py-1.5 rounded bg-noc-base border border-noc-border text-xs text-noc-text-secondary hover:text-noc-text-primary disabled:opacity-50"
              >
                Cancel
              </button>

              <button
                onClick={confirmModal === 'ACKNOWLEDGE' ? executeAcknowledge : executeResolve}
                disabled={actionInProgress}
                className={`px-4 py-1.5 rounded text-white text-xs font-semibold shadow-sm transition disabled:opacity-50 ${
                  confirmModal === 'ACKNOWLEDGE'
                    ? 'bg-amber-600 hover:bg-amber-500'
                    : 'bg-emerald-600 hover:bg-emerald-500'
                }`}
              >
                {actionInProgress
                  ? 'Committing...'
                  : confirmModal === 'ACKNOWLEDGE'
                  ? 'Confirm Acknowledge'
                  : 'Confirm Resolution'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IncidentsPage;

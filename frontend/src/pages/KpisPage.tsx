import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Gauge,
  Play,
  Radio,
  RefreshCw,
  Zap,
} from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { MetricCard } from '@/components/common/MetricCard';
import { ErrorState } from '@/components/common/ErrorState';
import { SimpleLineChart } from '@/components/common/SimpleLineChart';
import { apiClient } from '@/api/client';
import {
  DetectionRuleResponse,
  KPISnapshotResponse,
  TopologyResponse,
} from '@/types/api';
import { useWebSocketSubscription } from '@/websocket/useWebSocket';
import { WsEventType } from '@/types/websocket';
import {
  evaluateMetricStatus,
  getActiveThreshold,
  getActiveThresholdLabel,
  getMetricSubtitle,
} from '@/utils/kpiEvaluator';

function renderRuleBadge(
  rule: DetectionRuleResponse | undefined,
  nodeType: string | undefined,
  unit: string
) {
  if (!rule) {
    return <span className="text-[11px] font-mono text-noc-text-muted">Rule unavailable</span>;
  }
  if (!rule.enabled) {
    return <span className="text-[11px] font-mono text-noc-text-muted">Rule inactive</span>;
  }
  if (rule.node_types && (!nodeType || !rule.node_types.includes(nodeType))) {
    return (
      <span className="text-[11px] font-mono text-noc-text-muted">
        N/A for {nodeType || 'node'}
      </span>
    );
  }
  return (
    <span className="text-[11px] font-mono text-amber-400">
      Threshold {rule.operator} {rule.threshold} {unit}
    </span>
  );
}

export const KpisPage: React.FC = () => {
  const [snapshots, setSnapshots] = useState<KPISnapshotResponse[]>([]);
  const [totalSnapshots, setTotalSnapshots] = useState<number>(0);
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [rules, setRules] = useState<DetectionRuleResponse[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string>('CELL-01');
  const [selectedType, setSelectedType] = useState<string>('ALL');
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generationNotice, setGenerationNotice] = useState<string | null>(null);

  // Authoritative rules map from backend
  const rulesMap = useMemo(() => {
    const map = new Map<string, DetectionRuleResponse>();
    rules.forEach((r) => map.set(r.rule_id, r));
    return map;
  }, [rules]);

  const ruleAvail = rulesMap.get('RULE-AVAIL-CRIT');
  const ruleDrop = rulesMap.get('RULE-DROP-CRIT');
  const ruleLat = rulesMap.get('RULE-LAT-MAJOR');
  const rulePrb = rulesMap.get('RULE-PRB-MAJOR');
  const ruleSinr = rulesMap.get('RULE-SINR-MAJOR');
  const ruleRsrp = rulesMap.get('RULE-RSRP-WARN');
  const ruleTp = rulesMap.get('RULE-TP-WARN');

  // Load Topology, Telemetry, and Detection Rules
  const fetchTelemetry = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [telemRes, topoRes, rulesRes] = await Promise.all([
        apiClient.getTelemetry({ limit: 500 }),
        apiClient.getTopology(),
        apiClient.getDetectionRules(),
      ]);
      setSnapshots(telemRes.items);
      setTotalSnapshots(telemRes.total);
      setTopology(topoRes);
      setRules(rulesRes.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to query telemetry store');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTelemetry();
  }, [fetchTelemetry]);

  // Handle explicit generation step
  const handleGenerateStep = async () => {
    if (generating) return;
    setGenerating(true);
    setError(null);
    setGenerationNotice(null);
    try {
      const res = await apiClient.generateTelemetryStep();
      setGenerationNotice(
        `Generated 1 simulation cycle (${res.generated_count} node snapshots) at ${new Date(
          res.timestamp
        ).toLocaleTimeString()} UTC.`
      );
      // Fetch latest telemetry to reflect in UI
      await fetchTelemetry();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Telemetry step generation failed');
    } finally {
      setGenerating(false);
    }
  };

  // Re-fetch on live WebSocket telemetry events
  useWebSocketSubscription(WsEventType.TELEMETRY_SNAPSHOT, () => {
    apiClient.getTelemetry({ limit: 500 }).then((res) => {
      setSnapshots(res.items);
      setTotalSnapshots(res.total);
    }).catch(() => {});
  });

  // Filter available nodes by selected type
  const availableNodes = useMemo(() => {
    if (!topology) return [];
    if (selectedType === 'ALL') return topology.nodes;
    return topology.nodes.filter((n) => n.node_type === selectedType);
  }, [topology, selectedType]);

  // Selected node metadata
  const selectedNode = useMemo(() => {
    return topology?.nodes.find((n) => n.node_id === selectedNodeId) || null;
  }, [topology, selectedNodeId]);

  // Filter snapshots for selected node and sort chronologically (oldest to newest for trend chart)
  const nodeSnapshots = useMemo(() => {
    return snapshots
      .filter((s) => s.node_id === selectedNodeId)
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }, [snapshots, selectedNodeId]);

  const latestSnapshot = useMemo(() => {
    return nodeSnapshots.length > 0 ? nodeSnapshots[nodeSnapshots.length - 1] : null;
  }, [nodeSnapshots]);

  // Evaluated status for each metric
  const availEval = useMemo(() => {
    return evaluateMetricStatus(
      latestSnapshot?.reliability.availability_pct,
      ruleAvail,
      selectedNode?.node_type
    );
  }, [latestSnapshot, ruleAvail, selectedNode]);

  const dropEval = useMemo(() => {
    return evaluateMetricStatus(
      latestSnapshot?.reliability.connection_drop_rate_pct,
      ruleDrop,
      selectedNode?.node_type
    );
  }, [latestSnapshot, ruleDrop, selectedNode]);

  const latEval = useMemo(() => {
    return evaluateMetricStatus(
      latestSnapshot?.performance.latency_ms,
      ruleLat,
      selectedNode?.node_type
    );
  }, [latestSnapshot, ruleLat, selectedNode]);

  const tpEval = useMemo(() => {
    return evaluateMetricStatus(
      latestSnapshot?.performance.throughput_mbps,
      ruleTp,
      selectedNode?.node_type
    );
  }, [latestSnapshot, ruleTp, selectedNode]);

  return (
    <div>
      <PageHeader
        title="KPI Monitoring & Telemetry Stream"
        description="Radio frequency, transport, and service reliability metrics generated by the NEXUS synthetic simulation pipeline."
        breadcrumbs={[{ label: 'NOC' }, { label: 'KPIs & Telemetry' }]}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={handleGenerateStep}
              disabled={generating}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-sm transition disabled:opacity-50"
              title="Invokes the existing backend SyntheticTelemetryGenerator to produce 1 deterministic step"
            >
              <Play className={`w-3.5 h-3.5 ${generating ? 'animate-pulse' : ''}`} />
              {generating ? 'Generating Step...' : 'Generate One Telemetry Step'}
            </button>

            <button
              onClick={fetchTelemetry}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-noc-surface border border-noc-border hover:bg-noc-surface-hover text-xs font-medium text-noc-text-primary transition disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        }
      />

      {/* Synthetic simulation disclaimer note */}
      <div className="p-3 mb-6 rounded-lg bg-blue-950/30 border border-blue-900/50 flex items-start gap-3 text-xs">
        <Radio className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold text-blue-300">
            Simulated Network Telemetry Engine (In-Memory Buffer)
          </p>
          <p className="text-noc-text-secondary text-[11px] leading-relaxed">
            All metrics shown below are produced deterministically by the NEXUS synthetic telemetry generator. In accordance with architectural principles, telemetry generation is triggered exclusively via deliberate operator action. Snapshots are held in a bounded ring-buffer store and are discarded upon backend process restart.
          </p>
        </div>
      </div>

      {generationNotice && (
        <div className="p-3 mb-6 rounded-lg bg-emerald-950/30 border border-emerald-900/50 text-emerald-300 text-xs font-mono">
          ✓ {generationNotice}
        </div>
      )}

      {error && (
        <div className="mb-6">
          <ErrorState title="Telemetry Error" message={error} onRetry={fetchTelemetry} />
        </div>
      )}

      {/* Node & Metric Filter Bar */}
      <div className="bg-noc-surface border border-noc-border rounded-lg p-4 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-noc-text-muted font-medium">Node Tier:</span>
            <select
              value={selectedType}
              onChange={(e) => {
                setSelectedType(e.target.value);
                const matching = topology?.nodes.filter(
                  (n) => e.target.value === 'ALL' || n.node_type === e.target.value
                );
                if (matching && matching.length > 0) {
                  setSelectedNodeId(matching[0].node_id);
                }
              }}
              className="px-2 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-primary text-xs focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="ALL">All Tiers</option>
              <option value="CORE">Core (1)</option>
              <option value="AGGREGATION">Aggregation (2)</option>
              <option value="SITE">Site (6)</option>
              <option value="CELL">Cell (18)</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-noc-text-muted font-medium">Reporting Node:</span>
            <select
              value={selectedNodeId}
              onChange={(e) => setSelectedNodeId(e.target.value)}
              className="px-3 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-primary text-xs font-mono font-semibold focus:outline-none focus:border-blue-500"
            >
              {availableNodes.map((n) => (
                <option key={n.node_id} value={n.node_id}>
                  {n.node_id} ({n.node_type})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono text-noc-text-muted">
          <span>Total Snapshots in Store: <strong className="text-noc-text-primary">{totalSnapshots}</strong></span>
          <span>Observations for {selectedNodeId}: <strong className="text-noc-text-primary">{nodeSnapshots.length}</strong></span>
        </div>
      </div>

      {/* Empty State when no snapshots exist yet */}
      {totalSnapshots === 0 ? (
        <div className="bg-noc-surface border border-noc-border rounded-lg p-8 mb-6">
          <div className="max-w-md mx-auto text-center space-y-4">
            <div className="w-12 h-12 mx-auto rounded-full bg-noc-base border border-noc-border flex items-center justify-center text-blue-400">
              <Activity className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-noc-text-primary">
                Telemetry Generation Has Not Yet Been Triggered
              </h3>
              <p className="text-xs text-noc-text-muted mt-1 leading-relaxed">
                The NEXUS telemetry pipeline does not run uncontrolled background loops at startup. Click the button below to generate the first discrete simulation cycle for all 27 topology nodes.
              </p>
            </div>
            <button
              onClick={handleGenerateStep}
              disabled={generating}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-sm transition disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5" />
              {generating ? 'Generating Simulation Step...' : 'Generate First Telemetry Step'}
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Latest Observation KPI Cards for Selected Node */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <MetricCard
              title="Service Availability"
              value={latestSnapshot ? `${latestSnapshot.reliability.availability_pct.toFixed(1)}%` : 'N/A'}
              unit="%"
              subtitle={getMetricSubtitle(ruleAvail, availEval, selectedNode?.node_type, '%')}
              status={availEval.status}
              icon={Activity}
              loading={loading}
            />

            <MetricCard
              title="Connection Drop Rate"
              value={latestSnapshot ? `${latestSnapshot.reliability.connection_drop_rate_pct.toFixed(2)}%` : 'N/A'}
              unit="%"
              subtitle={getMetricSubtitle(ruleDrop, dropEval, selectedNode?.node_type, '%')}
              status={dropEval.status}
              icon={AlertTriangle}
              loading={loading}
            />

            <MetricCard
              title="Round-Trip Latency"
              value={latestSnapshot ? `${latestSnapshot.performance.latency_ms.toFixed(1)} ms` : 'N/A'}
              unit="ms"
              subtitle={getMetricSubtitle(ruleLat, latEval, selectedNode?.node_type, 'ms')}
              status={latEval.status}
              icon={Gauge}
              loading={loading}
            />

            <MetricCard
              title="Transport Throughput"
              value={latestSnapshot ? `${latestSnapshot.performance.throughput_mbps.toFixed(1)} Mbps` : 'N/A'}
              unit="Mbps"
              subtitle={getMetricSubtitle(ruleTp, tpEval, selectedNode?.node_type, 'Mbps')}
              status={tpEval.status}
              icon={Zap}
              loading={loading}
            />
          </div>

          {/* Timeseries Trend Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Availability Chart */}
            <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-noc-border">
                <h4 className="text-xs font-semibold text-noc-text-primary uppercase tracking-wider">
                  availability_pct (Service Availability)
                </h4>
                {renderRuleBadge(ruleAvail, selectedNode?.node_type, '%')}
              </div>
              <SimpleLineChart
                data={nodeSnapshots.map((s) => ({
                  timestamp: s.timestamp,
                  value: s.reliability.availability_pct,
                }))}
                metricName="availability_pct"
                unit="%"
                threshold={getActiveThreshold(ruleAvail, selectedNode?.node_type)}
                thresholdLabel={getActiveThresholdLabel(ruleAvail, selectedNode?.node_type)}
                color="#10b981"
              />
            </div>

            {/* Latency Chart */}
            <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-noc-border">
                <h4 className="text-xs font-semibold text-noc-text-primary uppercase tracking-wider">
                  latency_ms (Round-Trip Latency)
                </h4>
                {renderRuleBadge(ruleLat, selectedNode?.node_type, 'ms')}
              </div>
              <SimpleLineChart
                data={nodeSnapshots.map((s) => ({
                  timestamp: s.timestamp,
                  value: s.performance.latency_ms,
                }))}
                metricName="latency_ms"
                unit="ms"
                threshold={getActiveThreshold(ruleLat, selectedNode?.node_type)}
                thresholdLabel={getActiveThresholdLabel(ruleLat, selectedNode?.node_type)}
                color="#38bdf8"
              />
            </div>

            {/* Connection Drop Rate Chart */}
            <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-noc-border">
                <h4 className="text-xs font-semibold text-noc-text-primary uppercase tracking-wider">
                  connection_drop_rate_pct (Drop Rate)
                </h4>
                {renderRuleBadge(ruleDrop, selectedNode?.node_type, '%')}
              </div>
              <SimpleLineChart
                data={nodeSnapshots.map((s) => ({
                  timestamp: s.timestamp,
                  value: s.reliability.connection_drop_rate_pct,
                }))}
                metricName="connection_drop_rate_pct"
                unit="%"
                threshold={getActiveThreshold(ruleDrop, selectedNode?.node_type)}
                thresholdLabel={getActiveThresholdLabel(ruleDrop, selectedNode?.node_type)}
                color="#f87171"
              />
            </div>

            {/* Throughput Chart */}
            <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-noc-border">
                <h4 className="text-xs font-semibold text-noc-text-primary uppercase tracking-wider">
                  throughput_mbps (Throughput)
                </h4>
                {renderRuleBadge(ruleTp, selectedNode?.node_type, 'Mbps')}
              </div>
              <SimpleLineChart
                data={nodeSnapshots.map((s) => ({
                  timestamp: s.timestamp,
                  value: s.performance.throughput_mbps,
                }))}
                metricName="throughput_mbps"
                unit="Mbps"
                threshold={getActiveThreshold(ruleTp, selectedNode?.node_type)}
                thresholdLabel={getActiveThresholdLabel(ruleTp, selectedNode?.node_type)}
                color="#a78bfa"
              />
            </div>
          </div>

          {/* Radio KPIs Section for Radio Cells */}
          {selectedNode?.node_type !== 'CELL' ? (
            <div className="bg-noc-surface border border-noc-border rounded-lg p-4 mb-6 text-xs text-noc-text-muted flex items-center gap-2">
              <Radio className="w-4 h-4 text-noc-text-muted shrink-0" />
              <span>
                Node <strong className="text-noc-text-primary font-mono">{selectedNodeId}</strong> is a{' '}
                <strong className="text-noc-text-primary">{selectedNode?.node_type || 'non-radio'}</strong> node.
                Radio frequency and spectrum measurements (RSRP, SINR, PRB utilization) apply exclusively to CELL nodes.
              </span>
            </div>
          ) : !latestSnapshot?.radio ? (
            <div className="bg-noc-surface border border-noc-border rounded-lg p-4 mb-6 text-xs text-amber-400 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>
                No radio frequency measurements recorded for <strong className="font-mono">{selectedNodeId}</strong> (Insufficient telemetry).
              </span>
            </div>
          ) : (
            <div className="bg-noc-surface border border-noc-border rounded-lg p-5 mb-6">
              <div className="flex items-center justify-between pb-3 mb-4 border-b border-noc-border">
                <div className="flex items-center gap-2">
                  <Radio className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-semibold text-noc-text-primary">
                    Radio Frequency & Spectrum KPIs ({selectedNodeId})
                  </h3>
                </div>
                <span className="text-xs font-mono text-noc-text-muted">
                  Physical Resource Block & RF Signal Metrics
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <div className="flex items-center justify-between pb-1 mb-1">
                    <span className="text-xs font-mono text-noc-text-secondary">
                      rsrp_dbm (Reference Signal Received Power)
                    </span>
                    {renderRuleBadge(ruleRsrp, selectedNode?.node_type, 'dBm')}
                  </div>
                  <SimpleLineChart
                    data={nodeSnapshots
                      .filter((s) => s.radio !== null)
                      .map((s) => ({
                        timestamp: s.timestamp,
                        value: s.radio!.rsrp_dbm,
                      }))}
                    metricName="rsrp_dbm"
                    unit="dBm"
                    threshold={getActiveThreshold(ruleRsrp, selectedNode?.node_type)}
                    thresholdLabel={getActiveThresholdLabel(ruleRsrp, selectedNode?.node_type)}
                    color="#f59e0b"
                    height={140}
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between pb-1 mb-1">
                    <span className="text-xs font-mono text-noc-text-secondary">
                      sinr_db (Signal-to-Interference-plus-Noise Ratio)
                    </span>
                    {renderRuleBadge(ruleSinr, selectedNode?.node_type, 'dB')}
                  </div>
                  <SimpleLineChart
                    data={nodeSnapshots
                      .filter((s) => s.radio !== null)
                      .map((s) => ({
                        timestamp: s.timestamp,
                        value: s.radio!.sinr_db,
                      }))}
                    metricName="sinr_db"
                    unit="dB"
                    threshold={getActiveThreshold(ruleSinr, selectedNode?.node_type)}
                    thresholdLabel={getActiveThresholdLabel(ruleSinr, selectedNode?.node_type)}
                    color="#38bdf8"
                    height={140}
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between pb-1 mb-1">
                    <span className="text-xs font-mono text-noc-text-secondary">
                      prb_utilization_pct (PRB Resource Utilization)
                    </span>
                    {renderRuleBadge(rulePrb, selectedNode?.node_type, '%')}
                  </div>
                  <SimpleLineChart
                    data={nodeSnapshots
                      .filter((s) => s.radio !== null)
                      .map((s) => ({
                        timestamp: s.timestamp,
                        value: s.radio!.prb_utilization_pct,
                      }))}
                    metricName="prb_utilization_pct"
                    unit="%"
                    threshold={getActiveThreshold(rulePrb, selectedNode?.node_type)}
                    thresholdLabel={getActiveThresholdLabel(rulePrb, selectedNode?.node_type)}
                    color="#ec4899"
                    height={140}
                  />
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default KpisPage;

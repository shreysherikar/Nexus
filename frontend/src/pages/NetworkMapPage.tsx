import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Filter,
  Layers,
  MapPin,
  RefreshCw,
  Search,
  Server,
} from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { OperationalStatus, StatusBadge } from '@/components/common/StatusBadge';
import { SeverityBadge } from '@/components/common/SeverityBadge';
import { apiClient } from '@/api/client';
import {
  AlarmResponse,
  KPISnapshotResponse,
  TopologyNodeResponse,
  TopologyResponse,
} from '@/types/api';
import { useWebSocketSubscription } from '@/websocket/useWebSocket';
import { TopologyStatusChangedPayload, WsEventType } from '@/types/websocket';

export const NetworkMapPage: React.FC = () => {
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Search
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');

  // Hierarchy expand / collapse state
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set(['CORE-01', 'AGG-01', 'AGG-02']));

  // Selected Node & details
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>('CORE-01');
  const [selectedNodeTelemetry, setSelectedNodeTelemetry] = useState<KPISnapshotResponse | null>(null);
  const [selectedNodeAlarms, setSelectedNodeAlarms] = useState<AlarmResponse[]>([]);
  const [loadingNodeDetails, setLoadingNodeDetails] = useState(false);

  // Active view tab: Logical Hierarchy vs Geographic Map
  const [activeTab, setActiveTab] = useState<'logical' | 'geographic'>('logical');

  const fetchTopology = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getTopology();
      setTopology(data);
      if (!selectedNodeId && data.nodes.length > 0) {
        setSelectedNodeId(data.nodes[0].node_id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to query topology registry');
    } finally {
      setLoading(false);
    }
  }, [selectedNodeId]);

  useEffect(() => {
    fetchTopology();
  }, [fetchTopology]);

  // Fetch selected node extra details (telemetry & alarms)
  useEffect(() => {
    if (!selectedNodeId) {
      setSelectedNodeTelemetry(null);
      setSelectedNodeAlarms([]);
      return;
    }

    let isMounted = true;
    setLoadingNodeDetails(true);

    Promise.all([
      apiClient.getTelemetry({ node_id: selectedNodeId, limit: 1 }),
      apiClient.getAlarms({ node_id: selectedNodeId, limit: 10 }),
    ])
      .then(([telemRes, alarmsRes]) => {
        if (!isMounted) return;
        setSelectedNodeTelemetry(telemRes.items.length > 0 ? telemRes.items[0] : null);
        setSelectedNodeAlarms(alarmsRes.items);
      })
      .catch(() => {
        if (!isMounted) return;
        setSelectedNodeTelemetry(null);
        setSelectedNodeAlarms([]);
      })
      .finally(() => {
        if (isMounted) setLoadingNodeDetails(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedNodeId]);

  // Listen to live topology status updates
  useWebSocketSubscription<TopologyStatusChangedPayload>(
    WsEventType.TOPOLOGY_STATUS_CHANGED,
    (payload) => {
      setTopology((prev) => {
        if (!prev) return prev;
        const updated = prev.nodes.map((n) =>
          n.node_id === payload.node_id ? { ...n, status: payload.new_status } : n
        );
        return { ...prev, nodes: updated };
      });
    }
  );

  const toggleExpand = (nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  const selectedNode = useMemo(() => {
    return topology?.nodes.find((n) => n.node_id === selectedNodeId) ?? null;
  }, [topology, selectedNodeId]);

  // Nodes with genuine coordinates
  const nodesWithCoordinates = useMemo(() => {
    return topology?.nodes.filter((n) => n.latitude !== null && n.longitude !== null) ?? [];
  }, [topology]);

  // Hierarchy tree lookup
  const nodeMap = useMemo(() => {
    const map = new Map<string, TopologyNodeResponse>();
    if (topology) {
      for (const n of topology.nodes) {
        map.set(n.node_id, n);
      }
    }
    return map;
  }, [topology]);

  // Filtered nodes matching search and status/type filter
  const filteredNodes = useMemo(() => {
    if (!topology) return [];
    return topology.nodes.filter((n) => {
      const matchSearch =
        searchQuery === '' || n.node_id.toLowerCase().includes(searchQuery.toLowerCase());
      const matchType = typeFilter === 'ALL' || n.node_type === typeFilter;
      const matchStatus = statusFilter === 'ALL' || n.status === statusFilter;
      return matchSearch && matchType && matchStatus;
    });
  }, [topology, searchQuery, typeFilter, statusFilter]);

  // Root nodes (parent_id is null)
  const rootNodes = useMemo(() => {
    return topology?.nodes.filter((n) => n.parent_id === null) ?? [];
  }, [topology]);

  return (
    <div>
      <PageHeader
        title="Network Topology & Geographic Hierarchy"
        description="Logical transport tree, structural parent-child links, and geographic spatial distribution for the 27-node network."
        breadcrumbs={[{ label: 'NOC' }, { label: 'Network Map' }]}
        actions={
          <div className="flex items-center gap-2">
            <div className="flex items-center bg-noc-base border border-noc-border rounded p-0.5 text-xs">
              <button
                onClick={() => setActiveTab('logical')}
                className={`px-3 py-1 rounded font-medium transition ${
                  activeTab === 'logical'
                    ? 'bg-blue-600 text-white'
                    : 'text-noc-text-secondary hover:text-noc-text-primary'
                }`}
              >
                Logical Hierarchy
              </button>
              <button
                onClick={() => setActiveTab('geographic')}
                className={`px-3 py-1 rounded font-medium transition ${
                  activeTab === 'geographic'
                    ? 'bg-blue-600 text-white'
                    : 'text-noc-text-secondary hover:text-noc-text-primary'
                }`}
              >
                Geographic Map
              </button>
            </div>

            <button
              onClick={fetchTopology}
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
          <ErrorState title="Topology Load Failed" message={error} onRetry={fetchTopology} />
        </div>
      )}

      {/* Main View Area */}
      {activeTab === 'geographic' ? (
        <div className="mb-6">
          {nodesWithCoordinates.length === 0 ? (
            <div className="bg-noc-surface border border-noc-border rounded-lg p-6">
              <EmptyState
                title="Geographic Coordinates Not Configured"
                description="The reference simulated network topology models complete logical transport hierarchy, parent-child relationships, and synthetic radio telemetry. Physical GPS coordinates (latitude/longitude) are currently null in the backend registry."
                icon={MapPin}
                note="Per NEXUS engineering principles, map markers and physical coordinates are never fabricated. Once genuine coordinates are provided through an approved configuration path, Leaflet map markers will automatically plot them here."
              />
            </div>
          ) : (
            <div className="bg-noc-surface border border-noc-border rounded-lg p-5">
              <div className="flex items-center justify-between pb-3 mb-4 border-b border-noc-border">
                <div className="flex items-center gap-2">
                  <MapPin className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-semibold text-noc-text-primary">
                    Nodes with Verified Geographic Coordinates ({nodesWithCoordinates.length})
                  </h3>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {nodesWithCoordinates.map((node) => (
                  <div
                    key={node.node_id}
                    onClick={() => {
                      setSelectedNodeId(node.node_id);
                      setActiveTab('logical');
                    }}
                    className="p-3 rounded bg-noc-base border border-noc-border hover:border-blue-500/50 cursor-pointer transition"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-bold text-noc-text-primary">{node.node_id}</span>
                      <StatusBadge status={node.status.toLowerCase() as OperationalStatus} size="sm" />
                    </div>
                    <div className="text-xs text-noc-text-muted mt-2 font-mono">
                      Lat: {node.latitude?.toFixed(4)}, Lon: {node.longitude?.toFixed(4)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Logical Hierarchy View */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          {/* Left Column: Filterable Hierarchy Tree */}
          <div className="lg:col-span-2 bg-noc-surface border border-noc-border rounded-lg p-5 flex flex-col">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-noc-border">
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-semibold text-noc-text-primary">
                  Network Hierarchy Tree ({topology?.total_nodes ?? 0} Nodes)
                </h3>
              </div>

              {/* Tier Badges */}
              {topology && (
                <div className="flex items-center gap-2 text-[11px] font-mono text-noc-text-muted">
                  <span className="px-1.5 py-0.5 rounded bg-noc-base border border-noc-border">
                    Core: {topology.tiers['CORE'] || 0}
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-noc-base border border-noc-border">
                    Agg: {topology.tiers['AGGREGATION'] || 0}
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-noc-base border border-noc-border">
                    Sites: {topology.tiers['SITE'] || 0}
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-noc-base border border-noc-border">
                    Cells: {topology.tiers['CELL'] || 0}
                  </span>
                </div>
              )}
            </div>

            {/* Filter Bar */}
            <div className="flex flex-wrap items-center gap-3 py-3 border-b border-noc-border text-xs">
              <div className="relative flex-1 min-w-[160px]">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-noc-text-muted" />
                <input
                  type="text"
                  placeholder="Search by Node ID..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-primary placeholder:text-noc-text-muted text-xs focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="flex items-center gap-1.5">
                <Filter className="w-3.5 h-3.5 text-noc-text-muted" />
                <select
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  className="px-2 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-secondary text-xs focus:outline-none focus:border-blue-500"
                >
                  <option value="ALL">All Tiers</option>
                  <option value="CORE">Core</option>
                  <option value="AGGREGATION">Aggregation</option>
                  <option value="SITE">Site</option>
                  <option value="CELL">Cell</option>
                </select>

                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="px-2 py-1.5 rounded bg-noc-base border border-noc-border text-noc-text-secondary text-xs focus:outline-none focus:border-blue-500"
                >
                  <option value="ALL">All Statuses</option>
                  <option value="ONLINE">Online</option>
                  <option value="DEGRADED">Degraded</option>
                  <option value="OFFLINE">Offline</option>
                  <option value="MAINTENANCE">Maintenance</option>
                </select>
              </div>
            </div>

            {/* Tree View or Search Filtered List */}
            <div className="flex-1 overflow-y-auto mt-4 max-h-[560px] pr-1 space-y-1">
              {loading ? (
                <LoadingState message="Loading topology registry..." />
              ) : searchQuery || typeFilter !== 'ALL' || statusFilter !== 'ALL' ? (
                /* Flat filtered list when filtering */
                filteredNodes.length === 0 ? (
                  <div className="text-center py-10 text-xs text-noc-text-muted">
                    No nodes match the selected search or filter criteria.
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {filteredNodes.map((n) => (
                      <div
                        key={n.node_id}
                        onClick={() => setSelectedNodeId(n.node_id)}
                        className={`flex items-center justify-between p-2.5 rounded border text-xs cursor-pointer transition ${
                          selectedNodeId === n.node_id
                            ? 'bg-blue-950/40 border-blue-500 text-blue-200'
                            : 'bg-noc-base border-noc-border hover:bg-noc-surface-hover text-noc-text-primary'
                        }`}
                      >
                        <div className="flex items-center gap-2 font-mono">
                          <span className="font-semibold">{n.node_id}</span>
                          <span className="text-[10px] text-noc-text-muted px-1.5 py-0.2 rounded bg-noc-surface border border-noc-border">
                            {n.node_type}
                          </span>
                        </div>
                        <StatusBadge status={n.status.toLowerCase() as OperationalStatus} size="sm" />
                      </div>
                    ))}
                  </div>
                )
              ) : (
                /* Hierarchical Recursive Tree */
                rootNodes.map((root) => (
                  <TreeNodeItem
                    key={root.node_id}
                    node={root}
                    nodeMap={nodeMap}
                    expandedNodes={expandedNodes}
                    toggleExpand={toggleExpand}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={setSelectedNodeId}
                    depth={0}
                  />
                ))
              )}
            </div>
          </div>

          {/* Right Column: Node Details Panel */}
          <div className="bg-noc-surface border border-noc-border rounded-lg p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 pb-3 border-b border-noc-border">
                <Server className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-semibold text-noc-text-primary">Node Details</h3>
              </div>

              {selectedNode ? (
                <div className="mt-4 space-y-4">
                  {/* Node Header Info */}
                  <div className="p-3 rounded bg-noc-base border border-noc-border">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-base font-mono font-bold text-noc-text-primary">
                        {selectedNode.node_id}
                      </span>
                      <StatusBadge
                        status={selectedNode.status.toLowerCase() as OperationalStatus}
                        size="sm"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-mono text-noc-text-secondary mt-2">
                      <div>
                        <span className="text-noc-text-muted">Tier:</span> {selectedNode.node_type}
                      </div>
                      <div>
                        <span className="text-noc-text-muted">Parent:</span>{' '}
                        {selectedNode.parent_id ? (
                          <button
                            onClick={() => setSelectedNodeId(selectedNode.parent_id)}
                            className="text-blue-400 hover:underline"
                          >
                            {selectedNode.parent_id}
                          </button>
                        ) : (
                          <span className="text-noc-text-muted">Root Spine</span>
                        )}
                      </div>
                      <div>
                        <span className="text-noc-text-muted">Coordinates:</span>{' '}
                        {selectedNode.latitude !== null && selectedNode.longitude !== null
                          ? `${selectedNode.latitude.toFixed(4)}, ${selectedNode.longitude.toFixed(4)}`
                          : 'Not configured'}
                      </div>
                      <div>
                        <span className="text-noc-text-muted">Children:</span>{' '}
                        {selectedNode.children.length}
                      </div>
                    </div>
                  </div>

                  {/* Children Navigation List */}
                  {selectedNode.children.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-noc-text-muted uppercase tracking-wider mb-2">
                        Connected Subordinates ({selectedNode.children.length})
                      </h4>
                      <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                        {selectedNode.children.map((childId) => (
                          <button
                            key={childId}
                            onClick={() => setSelectedNodeId(childId)}
                            className="px-2 py-1 rounded bg-noc-base border border-noc-border hover:border-blue-500 font-mono text-xs text-noc-text-primary transition"
                          >
                            {childId}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Latest Telemetry Snapshot */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-xs font-semibold text-noc-text-muted uppercase tracking-wider">
                        Latest Telemetry Snapshot
                      </h4>
                      {selectedNodeTelemetry && (
                        <span className="text-[10px] font-mono text-noc-text-muted">
                          {new Date(selectedNodeTelemetry.timestamp).toLocaleTimeString()}
                        </span>
                      )}
                    </div>

                    {loadingNodeDetails ? (
                      <div className="p-3 text-center text-xs text-noc-text-muted">Loading telemetry...</div>
                    ) : selectedNodeTelemetry ? (
                      <div className="p-3 rounded bg-noc-base border border-noc-border space-y-2 text-xs font-mono">
                        <div className="flex justify-between">
                          <span className="text-noc-text-secondary">Availability:</span>
                          <span className="font-bold text-emerald-400">
                            {selectedNodeTelemetry.reliability.availability_pct.toFixed(2)}%
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-noc-text-secondary">Drop Rate:</span>
                          <span className="text-noc-text-primary">
                            {selectedNodeTelemetry.reliability.connection_drop_rate_pct.toFixed(2)}%
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-noc-text-secondary">Throughput:</span>
                          <span className="text-noc-text-primary">
                            {selectedNodeTelemetry.performance.throughput_mbps.toFixed(1)} Mbps
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-noc-text-secondary">Latency:</span>
                          <span className="text-noc-text-primary">
                            {selectedNodeTelemetry.performance.latency_ms.toFixed(1)} ms
                          </span>
                        </div>
                        {selectedNodeTelemetry.radio && (
                          <div className="pt-2 border-t border-noc-border grid grid-cols-2 gap-1 text-[11px]">
                            <div>
                              <span className="text-noc-text-muted">RSRP:</span>{' '}
                              {selectedNodeTelemetry.radio.rsrp_dbm.toFixed(1)} dBm
                            </div>
                            <div>
                              <span className="text-noc-text-muted">SINR:</span>{' '}
                              {selectedNodeTelemetry.radio.sinr_db.toFixed(1)} dB
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="p-3 rounded bg-noc-base/60 border border-noc-border text-center text-xs text-noc-text-muted">
                        No telemetry snapshots recorded for this node yet.
                      </div>
                    )}
                  </div>

                  {/* Related Active Alarms */}
                  <div>
                    <h4 className="text-xs font-semibold text-noc-text-muted uppercase tracking-wider mb-2">
                      Associated Alarms ({selectedNodeAlarms.length})
                    </h4>
                    {selectedNodeAlarms.length === 0 ? (
                      <div className="p-2.5 rounded bg-noc-base/60 border border-noc-border text-center text-xs text-noc-text-muted">
                        No active or historical alarms for this node.
                      </div>
                    ) : (
                      <div className="space-y-1.5 max-h-36 overflow-y-auto">
                        {selectedNodeAlarms.map((a) => (
                          <div
                            key={a.alarm_id}
                            className="p-2 rounded bg-noc-base border border-noc-border text-xs flex items-center justify-between font-mono"
                          >
                            <div>
                              <span className="font-semibold text-noc-text-primary block">{a.metric_name}</span>
                              <span className="text-[10px] text-noc-text-muted">{a.rule_id}</span>
                            </div>
                            <SeverityBadge severity={a.severity} size="sm" />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="mt-8 text-center text-xs text-noc-text-muted">
                  Select a node from the hierarchy tree to inspect details.
                </div>
              )}
            </div>

            <div className="mt-4 pt-3 border-t border-noc-border text-xs text-noc-text-muted">
              Reference simulated topology: 1 Core, 2 Aggregation, 6 Sites, 18 Cells (27 total).
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

interface TreeNodeItemProps {
  node: TopologyNodeResponse;
  nodeMap: Map<string, TopologyNodeResponse>;
  expandedNodes: Set<string>;
  toggleExpand: (id: string) => void;
  selectedNodeId: string | null;
  onSelectNode: (id: string) => void;
  depth: number;
}

const TreeNodeItem: React.FC<TreeNodeItemProps> = ({
  node,
  nodeMap,
  expandedNodes,
  toggleExpand,
  selectedNodeId,
  onSelectNode,
  depth,
}) => {
  const isExpanded = expandedNodes.has(node.node_id);
  const isSelected = selectedNodeId === node.node_id;
  const hasChildren = node.children.length > 0;

  return (
    <div>
      <div
        className={`flex items-center justify-between p-2 rounded text-xs cursor-pointer transition select-none ${
          isSelected
            ? 'bg-blue-950/60 border border-blue-500/80 text-blue-200'
            : 'bg-noc-base/50 hover:bg-noc-surface-hover border border-noc-border text-noc-text-primary'
        }`}
        style={{ marginLeft: `${depth * 18}px` }}
        onClick={() => onSelectNode(node.node_id)}
      >
        <div className="flex items-center gap-2 font-mono">
          {hasChildren ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleExpand(node.node_id);
              }}
              className="p-0.5 hover:text-blue-400 text-noc-text-muted"
            >
              {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            </button>
          ) : (
            <span className="w-3.5 h-3.5 inline-block" />
          )}

          <span className="font-semibold">{node.node_id}</span>
          <span className="text-[10px] text-noc-text-muted px-1.5 py-0.2 rounded bg-noc-surface border border-noc-border">
            {node.node_type}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {node.latitude !== null && node.longitude !== null && (
            <span title="Coordinates verified">
              <MapPin className="w-3 h-3 text-emerald-400" />
            </span>
          )}
          <StatusBadge status={node.status.toLowerCase() as OperationalStatus} size="sm" />
        </div>
      </div>

      {hasChildren && isExpanded && (
        <div className="mt-1 space-y-1">
          {node.children.map((childId) => {
            const childNode = nodeMap.get(childId);
            if (!childNode) return null;
            return (
              <TreeNodeItem
                key={childNode.node_id}
                node={childNode}
                nodeMap={nodeMap}
                expandedNodes={expandedNodes}
                toggleExpand={toggleExpand}
                selectedNodeId={selectedNodeId}
                onSelectNode={onSelectNode}
                depth={depth + 1}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};

export default NetworkMapPage;

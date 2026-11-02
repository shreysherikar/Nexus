/**
 * TypeScript API contracts matching NEXUS FastAPI backend models exactly.
 * Authoritative sources:
 * - src/nexus/incidents/schemas.py
 * - src/nexus/incidents/api.py
 */

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';

export interface HealthResponse {
  status: string;
}

export type IncidentStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';
export type IncidentSeverity = 'CRITICAL' | 'MAJOR' | 'MINOR' | 'WARNING' | 'INFORMATIONAL';
export type IncidentPriority = 'P1' | 'P2' | 'P3' | 'P4' | 'P5';
export type RootCauseType =
  | 'CELL_OUTAGE'
  | 'BACKHAUL_FAILURE'
  | 'RADIO_INTERFERENCE'
  | 'CELL_CONGESTION'
  | 'SITE_POWER_FAILURE'
  | 'UNKNOWN';

export type TargetType = 'NODE' | 'TRANSPORT_LINK' | 'UNKNOWN';
export type DetectionSource = 'THRESHOLD' | 'STATISTICAL' | 'ANOMALY';
export type AlarmSeverity = 'CRITICAL' | 'MAJOR' | 'WARNING';
export type AlarmStatus = 'ACTIVE' | 'CLEARED';

export interface SLABreachStatusResponse {
  ack_breached: boolean;
  resolve_breached: boolean;
  ack_time_seconds: number | null;
  resolve_time_seconds: number | null;
  evaluation_timestamp: string;
}

export interface EvidenceItemDTO {
  source_node_id: string;
  metric_name: string;
  observed_value: number;
  threshold_or_baseline?: number | null;
  reasoning: string;
  severity?: AlarmSeverity | null;
  evidence_source?: 'ALARM' | 'SNAPSHOT' | 'TOPOLOGY';
}

export interface HypothesisDTO {
  hypothesis_id: string;
  cause_type: RootCauseType | string;
  target_id: string;
  target_type: TargetType | string;
  confidence_score?: number | null;
  explanation: string;
  evidence_items?: EvidenceItemDTO[];
}

export interface IncidentResponse {
  incident_id: string;
  correlation_group_id: string;
  status: string;
  severity: string;
  priority: string;
  title: string;
  description: string;
  alarm_ids: string[];
  affected_node_ids: string[];
  suspected_cause_type?: string | null;
  suspected_target_id?: string | null;
  suspected_target_type?: string | null;
  rca_confidence_score?: number | null;
  rca_hypotheses: Array<Record<string, unknown>>;
  rca_evidence: Array<Record<string, unknown>>;
  created_at: string;
  ack_deadline: string;
  resolve_deadline: string;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  sla_status?: SLABreachStatusResponse | null;
}

export interface IncidentListResponse {
  items: IncidentResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface IncidentMetricsResponse {
  total_incidents: number;
  open_incident_count: number;
  incidents_by_status: Record<string, number>;
  incidents_by_severity: Record<string, number>;
  mtta_seconds: number | null;
  mttr_seconds: number | null;
  mttd_seconds: number | null;
  total_incidents_evaluated: number;
  compliant_incident_count: number;
  breached_incident_count: number;
  ack_sla_breached_count: number;
  resolve_sla_breached_count: number;
  sla_compliance_pct: number | null;
  as_of: string;
}

export interface TimelineEventResponse {
  event_id: string;
  incident_id: string;
  event_type: string;
  timestamp: string;
  actor: string;
  actor_type: string;
  details: Record<string, unknown>;
}

export interface AcknowledgeRequest {
  actor: string;
}

export interface ResolveRequest {
  actor: string;
  notes?: string | null;
}

export interface CorrelatedAlarmDTO {
  alarm_id: string;
  node_id: string;
  rule_id: string;
  metric_name: string;
  source: DetectionSource | string;
  severity: AlarmSeverity | string;
  current_value: number;
  threshold?: number | null;
  first_seen: string;
  last_seen: string;
  observation_count: number;
  status: AlarmStatus | string;
}

export interface CreateIncidentRequest {
  correlation_group_id: string;
  anchor_node_id?: string | null;
  root_cause_tier?: string | null;
  alarms: CorrelatedAlarmDTO[];
  time_window_start: string;
  time_window_end: string;
  correlation_reason?: string;
  suspected_cause_type?: RootCauseType | string | null;
  suspected_target_id?: string | null;
  suspected_target_type?: TargetType | string | null;
  rca_confidence_score?: number | null;
  hypotheses?: HypothesisDTO[];
  evidence_items?: EvidenceItemDTO[];
  created_by?: string;
}

export interface ApiErrorResponse {
  detail: string;
  error_code?: string;
  [key: string]: unknown;
}

// Topology contracts
export interface TopologyNodeResponse {
  node_id: string;
  node_type: 'CORE' | 'AGGREGATION' | 'SITE' | 'CELL' | string;
  parent_id: string | null;
  status: 'ONLINE' | 'OFFLINE' | 'DEGRADED' | 'MAINTENANCE' | string;
  latitude: number | null;
  longitude: number | null;
  children: string[];
}

export interface TopologyResponse {
  nodes: TopologyNodeResponse[];
  total_nodes: number;
  tiers: Record<string, number>;
}

// Telemetry contracts
export interface RadioMetricsResponse {
  rsrp_dbm: number;
  sinr_db: number;
  prb_utilization_pct: number;
}

export interface PerformanceMetricsResponse {
  throughput_mbps: number;
  latency_ms: number;
}

export interface ReliabilityMetricsResponse {
  connection_drop_rate_pct: number;
  availability_pct: number;
  handover_success_rate_pct: number | null;
}

export interface KPISnapshotResponse {
  node_id: string;
  timestamp: string;
  performance: PerformanceMetricsResponse;
  reliability: ReliabilityMetricsResponse;
  radio: RadioMetricsResponse | null;
}

export interface TelemetryListResponse {
  items: KPISnapshotResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface TelemetryGenerateStepResponse {
  generated_count: number;
  timestamp: string;
  message: string;
}

// Alarm contracts
export interface AlarmResponse {
  alarm_id: string;
  node_id: string;
  rule_id: string;
  metric_name: string;
  source: string;
  severity: AlarmSeverity | string;
  current_value: number;
  threshold: number | null;
  first_seen: string;
  last_seen: string;
  observation_count: number;
  status: AlarmStatus | string;
  cleared_at: string | null;
  description: string;
  evidence: Record<string, unknown>;
}

export interface AlarmListResponse {
  items: AlarmResponse[];
  total: number;
  limit: number;
  offset: number;
}

// Detection Rule contracts
export interface DetectionRuleResponse {
  rule_id: string;
  metric_name: string;
  operator: string;
  threshold: number;
  clear_threshold: number | null;
  severity: string;
  node_types: string[] | null;
  description: string;
  enabled: boolean;
}

export interface DetectionRuleListResponse {
  items: DetectionRuleResponse[];
  total: number;
}

// Fault Injection & Scenario contracts
export interface FaultInfo {
  fault_id: string;
  fault_type: string;
  target_id: string;
  severity: number;
  start_time: string;
  end_time: string;
  affected_nodes: string[];
  description: string | null;
}

export interface FaultScenarioInfo {
  id: string;
  scenario_id: string;
  name: string;
  description: string;
  fault_type: string;
  target_id: string;
  severity: number;
  affected_nodes: string[];
  is_active: boolean;
}

export interface FaultScenarioListResponse {
  items: FaultScenarioInfo[];
  total: number;
  active_scenario_id: string | null;
}

export interface ActiveScenarioResponse {
  active: boolean;
  scenario_id: string | null;
  scenario_key: string | null;
  name: string | null;
  description: string | null;
  faults: FaultInfo[];
  activated_at: string | null;
}

export interface ScenarioActionResponse {
  success: boolean;
  message: string;
  active_scenario: ActiveScenarioResponse;
}

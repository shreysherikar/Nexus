/**
 * WebSocket domain types, connection lifecycle states, and event schemas.
 */

export type WsConnectionStatus = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING';

export interface WsEventEnvelope<T = unknown> {
  type: string;
  timestamp: string;
  payload: T;
  sequence_id?: number;
}

export interface WsOptions {
  url?: string;
  autoConnect?: boolean;
  reconnectInterval?: number;
  maxReconnectInterval?: number;
  reconnectDecay?: number;
  maxReconnectAttempts?: number;
  heartbeatInterval?: number;
  onReconnectSnapshot?: () => Promise<void> | void;
}

export type WsEventListener<T = unknown> = (data: T, envelope: WsEventEnvelope<T>) => void;

export const WsEventType = {
  TELEMETRY_SNAPSHOT: 'TELEMETRY_SNAPSHOT',
  ALARM_CREATED: 'ALARM_CREATED',
  ALARM_UPDATED: 'ALARM_UPDATED',
  ALARM_CLEARED: 'ALARM_CLEARED',
  INCIDENT_CREATED: 'INCIDENT_CREATED',
  INCIDENT_ACKNOWLEDGED: 'INCIDENT_ACKNOWLEDGED',
  INCIDENT_RESOLVED: 'INCIDENT_RESOLVED',
  TOPOLOGY_STATUS_CHANGED: 'TOPOLOGY_STATUS_CHANGED',
  FAULT_STATUS_CHANGED: 'FAULT_STATUS_CHANGED',
} as const;

export type WsEventType = (typeof WsEventType)[keyof typeof WsEventType];

export interface TopologyStatusChangedPayload {
  node_id: string;
  old_status: string;
  new_status: string;
  node_type?: string;
  parent_id?: string | null;
}

export interface AlarmCreatedPayload {
  alarm_id: string;
  node_id: string;
  rule_id: string;
  metric_name: string;
  severity: string;
  current_value: number;
  threshold?: number | null;
  status: string;
  first_seen: string;
}

export interface AlarmUpdatedPayload {
  alarm_id: string;
  node_id: string;
  rule_id: string;
  metric_name: string;
  severity: string;
  current_value: number;
  threshold?: number | null;
  status: string;
  observation_count: number;
  last_seen: string;
}

export interface AlarmClearedPayload {
  alarm_id: string;
  node_id: string;
  rule_id: string;
  metric_name: string;
  cleared_at: string | null;
  status: string;
}

export interface IncidentCreatedPayload {
  incident_id: string;
  title: string;
  severity: string;
  status: string;
  affected_node_ids: string[];
  suspected_cause_type?: string | null;
  created_at: string;
}

export interface IncidentAcknowledgedPayload {
  incident_id: string;
  status: string;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;
}

export interface IncidentResolvedPayload {
  incident_id: string;
  status: string;
  resolved_by?: string | null;
  resolved_at?: string | null;
  notes?: string | null;
}

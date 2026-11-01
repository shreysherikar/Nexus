/**
 * NEXUS Typed REST API Client.
 *
 * Configurable via `VITE_API_BASE_URL`.
 * Supports caller request cancellation, timeout protection, typed endpoints,
 * and structured error handling matching FastAPI backend contracts.
 *
 * Authoritative Implemented Backend Endpoints:
 * - GET  /health
 * - GET  /api/v1/incidents?status={status}&severity={severity}&limit={limit}&offset={offset}
 * - POST /api/v1/incidents
 * - GET  /api/v1/incidents/metrics
 * - GET  /api/v1/incidents/{incident_id}
 * - POST /api/v1/incidents/{incident_id}/acknowledge
 * - POST /api/v1/incidents/{incident_id}/resolve
 * - GET  /api/v1/incidents/{incident_id}/timeline
 * - GET  /api/v1/topology
 * - GET  /api/v1/topology/nodes/{node_id}
 * - GET  /api/v1/telemetry?node_id={node_id}&node_type={node_type}&start_time={start_time}&end_time={end_time}&limit={limit}&offset={offset}
 * - POST /api/v1/telemetry/generate-step
 * - GET  /api/v1/alarms?node_id={node_id}&severity={severity}&status={status}&limit={limit}&offset={offset}
 * - GET  /api/v1/alarms/{alarm_id}
 * - GET  /api/v1/detection/rules
 * - WS   /ws/live
 */

import {
  AcknowledgeRequest,
  AlarmListResponse,
  AlarmResponse,
  ApiErrorResponse,
  CreateIncidentRequest,
  DetectionRuleListResponse,
  HealthResponse,
  IncidentListResponse,
  IncidentMetricsResponse,
  IncidentResponse,
  ResolveRequest,
  TelemetryGenerateStepResponse,
  TelemetryListResponse,
  TimelineEventResponse,
  TopologyNodeResponse,
  TopologyResponse,
} from '@/types/api';

export class ApiError extends Error {
  public readonly status: number;
  public readonly errorCode?: string;
  public readonly details?: unknown;

  constructor(status: number, message: string, errorCode?: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
    this.details = details;
  }
}

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
}

export class NexusApiClient {
  private readonly baseUrl: string;
  private readonly defaultTimeoutMs: number;

  constructor(baseUrl?: string, defaultTimeoutMs = 15000) {
    const envBase = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) || '';
    this.baseUrl = (baseUrl ?? envBase).replace(/\/+$/, '');
    this.defaultTimeoutMs = defaultTimeoutMs;
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { timeoutMs = this.defaultTimeoutMs, signal, headers, ...restOptions } = options;
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const url = `${this.baseUrl}${cleanPath}`;

    let isTimeout = false;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      isTimeout = true;
      controller.abort();
    }, timeoutMs);

    const abortListener = () => {
      // Aborted directly by caller
      controller.abort();
    };

    if (signal) {
      if (signal.aborted) {
        clearTimeout(timer);
        throw new ApiError(499, `Request to ${path} was cancelled by caller`, 'CLIENT_CANCELLED');
      }
      signal.addEventListener('abort', abortListener);
    }

    try {
      const response = await fetch(url, {
        ...restOptions,
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          ...headers,
        },
      });

      if (!response.ok) {
        let errBody: ApiErrorResponse | null = null;
        try {
          errBody = (await response.json()) as ApiErrorResponse;
        } catch {
          // Response body was not JSON
        }

        const message =
          errBody?.detail || `API request failed with status ${response.status} (${response.statusText})`;
        throw new ApiError(response.status, message, errBody?.error_code, errBody);
      }

      return (await response.json()) as T;
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        throw err;
      }
      if (err instanceof DOMException && err.name === 'AbortError') {
        if (isTimeout) {
          throw new ApiError(408, `Request to ${path} timed out after ${timeoutMs}ms`, 'REQUEST_TIMEOUT');
        }
        throw new ApiError(499, `Request to ${path} was cancelled by caller`, 'CLIENT_CANCELLED');
      }
      const message = err instanceof Error ? err.message : 'Unknown network failure';
      throw new ApiError(0, `Network failure connecting to ${url}: ${message}`);
    } finally {
      clearTimeout(timer);
      if (signal) {
        signal.removeEventListener('abort', abortListener);
      }
    }
  }

  // Health probe
  public async getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    return this.request<HealthResponse>('/health', { method: 'GET', signal });
  }

  // Incidents: uses exact limit/offset pagination matching FastAPI backend
  public async getIncidents(
    params?: {
      status?: string;
      severity?: string;
      limit?: number;
      offset?: number;
    },
    signal?: AbortSignal
  ): Promise<IncidentListResponse> {
    const query = new URLSearchParams();
    if (params) {
      if (params.status) query.set('status', params.status);
      if (params.severity) query.set('severity', params.severity);
      if (params.limit !== undefined && params.limit !== null) query.set('limit', String(params.limit));
      if (params.offset !== undefined && params.offset !== null) query.set('offset', String(params.offset));
    }
    const qs = query.toString();
    const endpoint = `/api/v1/incidents${qs ? `?${qs}` : ''}`;
    return this.request<IncidentListResponse>(endpoint, { method: 'GET', signal });
  }

  public async getIncidentById(incidentId: string, signal?: AbortSignal): Promise<IncidentResponse> {
    return this.request<IncidentResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}`, {
      method: 'GET',
      signal,
    });
  }

  public async getIncidentMetrics(signal?: AbortSignal): Promise<IncidentMetricsResponse> {
    return this.request<IncidentMetricsResponse>('/api/v1/incidents/metrics', {
      method: 'GET',
      signal,
    });
  }

  public async getIncidentTimeline(
    incidentId: string,
    signal?: AbortSignal
  ): Promise<TimelineEventResponse[]> {
    return this.request<TimelineEventResponse[]>(
      `/api/v1/incidents/${encodeURIComponent(incidentId)}/timeline`,
      { method: 'GET', signal }
    );
  }

  public async acknowledgeIncident(
    incidentId: string,
    data: AcknowledgeRequest,
    signal?: AbortSignal
  ): Promise<IncidentResponse> {
    return this.request<IncidentResponse>(
      `/api/v1/incidents/${encodeURIComponent(incidentId)}/acknowledge`,
      {
        method: 'POST',
        body: JSON.stringify(data),
        signal,
      }
    );
  }

  public async resolveIncident(
    incidentId: string,
    data: ResolveRequest,
    signal?: AbortSignal
  ): Promise<IncidentResponse> {
    return this.request<IncidentResponse>(
      `/api/v1/incidents/${encodeURIComponent(incidentId)}/resolve`,
      {
        method: 'POST',
        body: JSON.stringify(data),
        signal,
      }
    );
  }

  public async createIncident(
    data: CreateIncidentRequest,
    signal?: AbortSignal
  ): Promise<IncidentResponse> {
    return this.request<IncidentResponse>('/api/v1/incidents', {
      method: 'POST',
      body: JSON.stringify(data),
      signal,
    });
  }

  // Topology endpoints
  public async getTopology(signal?: AbortSignal): Promise<TopologyResponse> {
    return this.request<TopologyResponse>('/api/v1/topology', { method: 'GET', signal });
  }

  public async getTopologyNode(nodeId: string, signal?: AbortSignal): Promise<TopologyNodeResponse> {
    return this.request<TopologyNodeResponse>(`/api/v1/topology/nodes/${encodeURIComponent(nodeId)}`, {
      method: 'GET',
      signal,
    });
  }

  // Telemetry endpoints
  public async getTelemetry(
    params?: {
      node_id?: string;
      node_type?: string;
      start_time?: string;
      end_time?: string;
      limit?: number;
      offset?: number;
    },
    signal?: AbortSignal
  ): Promise<TelemetryListResponse> {
    const query = new URLSearchParams();
    if (params) {
      if (params.node_id) query.set('node_id', params.node_id);
      if (params.node_type) query.set('node_type', params.node_type);
      if (params.start_time) query.set('start_time', params.start_time);
      if (params.end_time) query.set('end_time', params.end_time);
      if (params.limit !== undefined && params.limit !== null) query.set('limit', String(params.limit));
      if (params.offset !== undefined && params.offset !== null) query.set('offset', String(params.offset));
    }
    const qs = query.toString();
    const endpoint = `/api/v1/telemetry${qs ? `?${qs}` : ''}`;
    return this.request<TelemetryListResponse>(endpoint, { method: 'GET', signal });
  }

  public async generateTelemetryStep(signal?: AbortSignal): Promise<TelemetryGenerateStepResponse> {
    return this.request<TelemetryGenerateStepResponse>('/api/v1/telemetry/generate-step', {
      method: 'POST',
      signal,
    });
  }

  // Alarm endpoints
  public async getAlarms(
    params?: {
      node_id?: string;
      severity?: string;
      status?: string;
      limit?: number;
      offset?: number;
    },
    signal?: AbortSignal
  ): Promise<AlarmListResponse> {
    const query = new URLSearchParams();
    if (params) {
      if (params.node_id) query.set('node_id', params.node_id);
      if (params.severity) query.set('severity', params.severity);
      if (params.status) query.set('status', params.status);
      if (params.limit !== undefined && params.limit !== null) query.set('limit', String(params.limit));
      if (params.offset !== undefined && params.offset !== null) query.set('offset', String(params.offset));
    }
    const qs = query.toString();
    const endpoint = `/api/v1/alarms${qs ? `?${qs}` : ''}`;
    return this.request<AlarmListResponse>(endpoint, { method: 'GET', signal });
  }

  public async getAlarmById(alarmId: string, signal?: AbortSignal): Promise<AlarmResponse> {
    return this.request<AlarmResponse>(`/api/v1/alarms/${encodeURIComponent(alarmId)}`, {
      method: 'GET',
      signal,
    });
  }

  // Detection rules endpoint
  public async getDetectionRules(signal?: AbortSignal): Promise<DetectionRuleListResponse> {
    return this.request<DetectionRuleListResponse>('/api/v1/detection/rules', {
      method: 'GET',
      signal,
    });
  }
}

// Singleton default client instance
export const apiClient = new NexusApiClient();

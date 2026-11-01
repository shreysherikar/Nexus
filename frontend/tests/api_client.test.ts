import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { NexusApiClient, ApiError } from '@/api/client';

describe('NexusApiClient', () => {
  let client: NexusApiClient;
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch);
    client = new NexusApiClient('http://test-nexus:8000', 1000);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('constructs correct URL and strips trailing slashes', () => {
    const c = new NexusApiClient('http://api.nexus.internal:8000///');
    expect(c.getBaseUrl()).toBe('http://api.nexus.internal:8000');
  });

  it('queries health endpoint successfully', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'healthy' }),
    });

    const res = await client.getHealth();
    expect(res).toEqual({ status: 'healthy' });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/health',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('queries incidents with limit and offset query parameters for pagination and filtering', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 40 }),
    });

    const res = await client.getIncidents({ status: 'OPEN', severity: 'CRITICAL', limit: 20, offset: 40 });
    expect(res).toEqual({ items: [], total: 0, limit: 20, offset: 40 });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/incidents?status=OPEN&severity=CRITICAL&limit=20&offset=40',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('queries incident metrics matching FastAPI IncidentMetricsResponse schema', async () => {
    const mockMetrics = {
      total_incidents: 10,
      open_incident_count: 3,
      incidents_by_status: { OPEN: 3, RESOLVED: 7 },
      incidents_by_severity: { CRITICAL: 2, MAJOR: 1 },
      mtta_seconds: 120.5,
      mttr_seconds: 450.0,
      mttd_seconds: 30.2,
      ack_sla_breached_count: 0,
      resolve_sla_breached_count: 1,
      as_of: '2026-10-31T20:00:00Z',
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockMetrics,
    });

    const res = await client.getIncidentMetrics();
    expect(res).toEqual(mockMetrics);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/incidents/metrics',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('sends acknowledge request matching backend schema { actor }', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ incident_id: 'INC-001', status: 'ACKNOWLEDGED' }),
    });

    await client.acknowledgeIncident('INC-001', { actor: 'noc-operator' });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/incidents/INC-001/acknowledge',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ actor: 'noc-operator' }),
      })
    );
  });

  it('sends resolve request with notes matching backend schema { actor, notes }', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ incident_id: 'INC-001', status: 'RESOLVED' }),
    });

    await client.resolveIncident('INC-001', {
      actor: 'noc-operator',
      notes: 'Fiber link restored and verified',
    });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/incidents/INC-001/resolve',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          actor: 'noc-operator',
          notes: 'Fiber link restored and verified',
        }),
      })
    );
  });

  it('handles HTTP error responses and parses structured API error', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: 'Incident INC-999 not found', error_code: 'INCIDENT_NOT_FOUND' }),
    });

    await expect(client.getIncidentById('INC-999')).rejects.toThrow(ApiError);
    try {
      await client.getIncidentById('INC-999');
    } catch (err) {
      if (err instanceof ApiError) {
        expect(err.status).toBe(404);
        expect(err.message).toBe('Incident INC-999 not found');
        expect(err.errorCode).toBe('INCIDENT_NOT_FOUND');
      }
    }
  });

  it('supports request timeout through internal AbortController returning 408 REQUEST_TIMEOUT', async () => {
    // Simulate a hung fetch that triggers the abort signal
    mockFetch.mockImplementation(
      (_url: string, options: { signal: AbortSignal }) =>
        new Promise((_, reject) => {
          options.signal.addEventListener('abort', () => {
            const err = new DOMException('The user aborted a request.', 'AbortError');
            reject(err);
          });
        })
    );

    const fastClient = new NexusApiClient('http://test-nexus:8000', 50);
    try {
      await fastClient.getHealth();
      expect.unreachable('Should have timed out');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      if (err instanceof ApiError) {
        expect(err.status).toBe(408);
        expect(err.errorCode).toBe('REQUEST_TIMEOUT');
        expect(err.message).toMatch(/timed out after 50ms/);
      }
    }
  });

  it('distinguishes external AbortSignal cancellation returning 499 CLIENT_CANCELLED', async () => {
    const controller = new AbortController();
    mockFetch.mockImplementation(
      (_url: string, options: { signal: AbortSignal }) =>
        new Promise((_, reject) => {
          options.signal.addEventListener('abort', () => {
            const err = new DOMException('The user aborted a request.', 'AbortError');
            reject(err);
          });
        })
    );

    const promise = client.getHealth(controller.signal);
    controller.abort();
    try {
      await promise;
      expect.unreachable('Should have aborted');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      if (err instanceof ApiError) {
        expect(err.status).toBe(499);
        expect(err.errorCode).toBe('CLIENT_CANCELLED');
        expect(err.message).toBe('Request to /health was cancelled by caller');
      }
    }
  });

  it('queries complete topology hierarchy', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        nodes: [{ node_id: 'CORE-01', node_type: 'CORE', parent_id: null, status: 'ONLINE', latitude: null, longitude: null, children: ['AGG-01'] }],
        total_nodes: 1,
        tiers: { CORE: 1 },
      }),
    });

    const res = await client.getTopology();
    expect(res.total_nodes).toBe(1);
    expect(res.nodes[0].node_id).toBe('CORE-01');
    expect(mockFetch).toHaveBeenCalledWith('http://test-nexus:8000/api/v1/topology', expect.objectContaining({ method: 'GET' }));
  });

  it('queries single topology node details', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        node_id: 'AGG-01',
        node_type: 'AGGREGATION',
        parent_id: 'CORE-01',
        status: 'ONLINE',
        latitude: null,
        longitude: null,
        children: ['SITE-01'],
      }),
    });

    const res = await client.getTopologyNode('AGG-01');
    expect(res.node_id).toBe('AGG-01');
    expect(mockFetch).toHaveBeenCalledWith('http://test-nexus:8000/api/v1/topology/nodes/AGG-01', expect.objectContaining({ method: 'GET' }));
  });

  it('queries telemetry snapshots with node and type filters', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 10, offset: 0 }),
    });

    const res = await client.getTelemetry({ node_id: 'CELL-01', node_type: 'CELL', limit: 10, offset: 0 });
    expect(res.items).toEqual([]);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/telemetry?node_id=CELL-01&node_type=CELL&limit=10&offset=0',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('triggers explicit telemetry step generation', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        generated_count: 27,
        timestamp: '2026-11-01T14:00:00Z',
        message: 'Step complete',
      }),
    });

    const res = await client.generateTelemetryStep();
    expect(res.generated_count).toBe(27);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/telemetry/generate-step',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('queries alarms with severity and status filters', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
    });

    const res = await client.getAlarms({ severity: 'CRITICAL', status: 'ACTIVE', limit: 50, offset: 0 });
    expect(res.items).toEqual([]);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/alarms?severity=CRITICAL&status=ACTIVE&limit=50&offset=0',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('queries single alarm by ID', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        alarm_id: 'ALM-1',
        node_id: 'CELL-01',
        rule_id: 'RULE-1',
        metric_name: 'latency_ms',
        source: 'THRESHOLD',
        severity: 'CRITICAL',
        current_value: 120,
        threshold: 80,
        first_seen: '2026-11-01T10:00:00Z',
        last_seen: '2026-11-01T10:05:00Z',
        observation_count: 5,
        status: 'ACTIVE',
        cleared_at: null,
        description: 'High latency',
        evidence: {},
      }),
    });

    const res = await client.getAlarmById('ALM-1');
    expect(res.alarm_id).toBe('ALM-1');
    expect(mockFetch).toHaveBeenCalledWith('http://test-nexus:8000/api/v1/alarms/ALM-1', expect.objectContaining({ method: 'GET' }));
  });

  it('queries detection rules from GET /api/v1/detection/rules', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        items: [
          {
            rule_id: 'RULE-AVAIL-CRIT',
            metric_name: 'availability_pct',
            operator: '<',
            threshold: 95.0,
            clear_threshold: 98.0,
            severity: 'CRITICAL',
            node_types: null,
            description: 'Service availability dropped below critical threshold',
            enabled: true,
          },
        ],
        total: 1,
      }),
    });

    const res = await client.getDetectionRules();
    expect(res.total).toBe(1);
    expect(res.items[0].rule_id).toBe('RULE-AVAIL-CRIT');
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test-nexus:8000/api/v1/detection/rules',
      expect.objectContaining({ method: 'GET' })
    );
  });
});

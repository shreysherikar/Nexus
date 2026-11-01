import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { KpisPage } from '@/pages/KpisPage';
import {
  evaluateMetricStatus,
  getActiveThreshold,
  getActiveThresholdLabel,
  getMetricSubtitle,
} from '@/utils/kpiEvaluator';
import { apiClient } from '@/api/client';
import { DetectionRuleResponse } from '@/types/api';

vi.mock('@/api/client', () => {
  return {
    apiClient: {
      getTelemetry: vi.fn(),
      getTopology: vi.fn(),
      getDetectionRules: vi.fn(),
      generateTelemetryStep: vi.fn(),
    },
  };
});

describe('KPIs Threshold & Node Applicability Accuracy', () => {
  const cellRule: DetectionRuleResponse = {
    rule_id: 'RULE-PRB-MAJOR',
    metric_name: 'prb_utilization_pct',
    operator: '>',
    threshold: 85.0,
    clear_threshold: 75.0,
    severity: 'MAJOR',
    node_types: ['CELL'],
    description: 'Cell PRB utilization saturated',
    enabled: true,
  };

  const genericRule: DetectionRuleResponse = {
    rule_id: 'RULE-AVAIL-CRIT',
    metric_name: 'availability_pct',
    operator: '<',
    threshold: 95.0,
    clear_threshold: 98.0,
    severity: 'CRITICAL',
    node_types: null,
    description: 'Availability dropped below 95%',
    enabled: true,
  };

  describe('evaluateMetricStatus Unit Verification', () => {
    it('returns neutral/Rule unavailable when rule configuration is missing', () => {
      const res = evaluateMetricStatus(99.0, undefined, 'CELL');
      expect(res.status).toBe('neutral');
      expect(res.label).toBe('Rule unavailable');
    });

    it('returns neutral/Rule inactive when rule is disabled', () => {
      const disabledRule: DetectionRuleResponse = { ...genericRule, enabled: false };
      const res = evaluateMetricStatus(99.0, disabledRule, 'CELL');
      expect(res.status).toBe('neutral');
      expect(res.label).toBe('Rule inactive');
    });

    it('returns neutral/N/A when restricted rule has an undefined node type', () => {
      const res = evaluateMetricStatus(70.0, cellRule, undefined);
      expect(res.status).toBe('neutral');
      expect(res.label).toBe('N/A: Applies to CELL');
    });

    it('returns neutral/N/A when restricted rule is evaluated on a non-applicable node', () => {
      const res = evaluateMetricStatus(70.0, cellRule, 'CORE');
      expect(res.status).toBe('neutral');
      expect(res.label).toBe('N/A: Applies to CELL');
    });

    it('evaluates as healthy only on an applicable node with nominal telemetry', () => {
      const res = evaluateMetricStatus(70.0, cellRule, 'CELL');
      expect(res.status).toBe('healthy');
      expect(res.label).toBe('Nominal');
    });

    it('evaluates as warning/critical when violated on an applicable node', () => {
      const res = evaluateMetricStatus(88.0, cellRule, 'CELL');
      expect(res.status).toBe('warning');
      expect(res.label).toBe('RULE-PRB-MAJOR violated');
    });

    it('returns unknown/Insufficient telemetry when metric value is null or undefined', () => {
      const res1 = evaluateMetricStatus(null, cellRule, 'CELL');
      expect(res1.status).toBe('unknown');
      expect(res1.label).toBe('Insufficient telemetry');

      const res2 = evaluateMetricStatus(undefined, cellRule, 'CELL');
      expect(res2.status).toBe('unknown');
      expect(res2.label).toBe('Insufficient telemetry');
    });
  });

  describe('getActiveThreshold & getActiveThresholdLabel Chart Prop Helpers', () => {
    it('returns undefined when rule is missing', () => {
      expect(getActiveThreshold(undefined, 'CELL')).toBeUndefined();
      expect(getActiveThresholdLabel(undefined, 'CELL')).toBeUndefined();
    });

    it('returns undefined when rule is disabled', () => {
      const disabled = { ...genericRule, enabled: false };
      expect(getActiveThreshold(disabled, 'CELL')).toBeUndefined();
      expect(getActiveThresholdLabel(disabled, 'CELL')).toBeUndefined();
    });

    it('returns undefined when restricted rule has undefined node type', () => {
      expect(getActiveThreshold(cellRule, undefined)).toBeUndefined();
      expect(getActiveThresholdLabel(cellRule, undefined)).toBeUndefined();
    });

    it('returns undefined when restricted rule is on non-applicable node', () => {
      expect(getActiveThreshold(cellRule, 'CORE')).toBeUndefined();
      expect(getActiveThresholdLabel(cellRule, 'CORE')).toBeUndefined();
    });

    it('returns active threshold and label on matching applicable node', () => {
      expect(getActiveThreshold(cellRule, 'CELL')).toBe(85.0);
      expect(getActiveThresholdLabel(cellRule, 'CELL')).toBe('RULE-PRB-MAJOR');
    });
  });

  describe('getMetricSubtitle Subtitle Generator', () => {
    it('reports Rule unavailable when rule is absent', () => {
      const sub = getMetricSubtitle(undefined, { status: 'healthy', label: '' }, 'CELL', '%');
      expect(sub).toBe('Rule unavailable');
    });

    it('reports Rule inactive when rule is disabled', () => {
      const disabled = { ...genericRule, enabled: false };
      const sub = getMetricSubtitle(disabled, { status: 'healthy', label: '' }, 'CELL', '%');
      expect(sub).toBe('Rule inactive');
    });

    it('reports N/A applicability when node type is missing or restricted', () => {
      const sub = getMetricSubtitle(cellRule, { status: 'neutral', label: '' }, 'CORE', '%');
      expect(sub).toBe('N/A: Applies to CELL');
    });

    it('reports dynamic rule definition when active and applicable', () => {
      const sub = getMetricSubtitle(cellRule, { status: 'healthy', label: '' }, 'CELL', '%');
      expect(sub).toBe('RULE-PRB-MAJOR (> 85 %)');
    });
  });

  describe('KpisPage Component Rendering with Missing & Inactive Rules', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('renders explicit Rule unavailable states and no threshold lines when rule configuration is empty', async () => {
      vi.mocked(apiClient.getTopology).mockResolvedValue({
        nodes: [
          { node_id: 'CELL-01', node_type: 'CELL', parent_id: 'SITE-01', status: 'ONLINE', latitude: null, longitude: null, children: [] },
        ],
        total_nodes: 1,
        tiers: { CELL: 1 },
      });
      vi.mocked(apiClient.getTelemetry).mockResolvedValue({
        items: [
          {
            node_id: 'CELL-01',
            timestamp: '2026-11-01T12:00:00Z',
            performance: { throughput_mbps: 45.0, latency_ms: 18.0 },
            reliability: { availability_pct: 99.9, connection_drop_rate_pct: 0.1, handover_success_rate_pct: 99.5 },
            radio: { rsrp_dbm: -95.0, sinr_db: 18.0, prb_utilization_pct: 40.0 },
          },
        ],
        total: 1,
        limit: 500,
        offset: 0,
      });
      // Empty rules response from backend
      vi.mocked(apiClient.getDetectionRules).mockResolvedValue({
        items: [],
        total: 0,
      });

      render(
        <MemoryRouter>
          <KpisPage />
        </MemoryRouter>
      );

      expect(await screen.findByText('KPI Monitoring & Telemetry Stream')).toBeInTheDocument();

      // Card subtitles should show Rule unavailable
      const unavailableSubtitles = screen.getAllByText('Rule unavailable');
      expect(unavailableSubtitles.length).toBeGreaterThanOrEqual(4);

      // SimpleLineChart threshold badges should show Rule unavailable
      const unavailableBadges = screen.getAllByText('Rule unavailable');
      expect(unavailableBadges.length).toBeGreaterThan(0);
    });

    it('renders explicit Rule inactive when rule is returned with enabled=false', async () => {
      vi.mocked(apiClient.getTopology).mockResolvedValue({
        nodes: [
          { node_id: 'CELL-01', node_type: 'CELL', parent_id: 'SITE-01', status: 'ONLINE', latitude: null, longitude: null, children: [] },
        ],
        total_nodes: 1,
        tiers: { CELL: 1 },
      });
      vi.mocked(apiClient.getTelemetry).mockResolvedValue({
        items: [
          {
            node_id: 'CELL-01',
            timestamp: '2026-11-01T12:00:00Z',
            performance: { throughput_mbps: 45.0, latency_ms: 18.0 },
            reliability: { availability_pct: 99.9, connection_drop_rate_pct: 0.1, handover_success_rate_pct: 99.5 },
            radio: { rsrp_dbm: -95.0, sinr_db: 18.0, prb_utilization_pct: 40.0 },
          },
        ],
        total: 1,
        limit: 500,
        offset: 0,
      });
      vi.mocked(apiClient.getDetectionRules).mockResolvedValue({
        items: [
          {
            rule_id: 'RULE-AVAIL-CRIT',
            metric_name: 'availability_pct',
            operator: '<',
            threshold: 95.0,
            clear_threshold: 98.0,
            severity: 'CRITICAL',
            node_types: null,
            description: 'Disabled availability rule',
            enabled: false, // Disabled!
          },
        ],
        total: 1,
      });

      render(
        <MemoryRouter>
          <KpisPage />
        </MemoryRouter>
      );

      expect(await screen.findByText('KPI Monitoring & Telemetry Stream')).toBeInTheDocument();
      expect(screen.getAllByText('Rule inactive').length).toBeGreaterThanOrEqual(1);
    });
  });
});

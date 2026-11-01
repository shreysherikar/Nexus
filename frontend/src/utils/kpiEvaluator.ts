import { DetectionRuleResponse } from '@/types/api';

export function evaluateMetricStatus(
  value: number | null | undefined,
  rule: DetectionRuleResponse | undefined,
  nodeType: string | undefined
): {
  status: 'healthy' | 'warning' | 'critical' | 'neutral' | 'unknown';
  label: string;
} {
  if (value === null || value === undefined || isNaN(value)) {
    return { status: 'unknown', label: 'Insufficient telemetry' };
  }
  if (!rule) {
    return { status: 'neutral', label: 'Rule unavailable' };
  }
  if (!rule.enabled) {
    return { status: 'neutral', label: 'Rule inactive' };
  }
  if (rule.node_types && (!nodeType || !rule.node_types.includes(nodeType))) {
    return { status: 'neutral', label: `N/A: Applies to ${rule.node_types.join(', ')}` };
  }

  let isViolated = false;
  if (rule.operator === '<' && value < rule.threshold) isViolated = true;
  else if (rule.operator === '<=' && value <= rule.threshold) isViolated = true;
  else if (rule.operator === '>' && value > rule.threshold) isViolated = true;
  else if (rule.operator === '>=' && value >= rule.threshold) isViolated = true;

  if (isViolated) {
    const s = rule.severity.toUpperCase();
    if (s === 'CRITICAL') return { status: 'critical', label: `${rule.rule_id} violated` };
    return { status: 'warning', label: `${rule.rule_id} violated` };
  }
  return { status: 'healthy', label: 'Nominal' };
}

export function getActiveThreshold(
  rule: DetectionRuleResponse | undefined,
  nodeType: string | undefined
): number | undefined {
  if (!rule || !rule.enabled) return undefined;
  if (rule.node_types && (!nodeType || !rule.node_types.includes(nodeType))) return undefined;
  return rule.threshold;
}

export function getActiveThresholdLabel(
  rule: DetectionRuleResponse | undefined,
  nodeType: string | undefined
): string | undefined {
  if (!rule || !rule.enabled) return undefined;
  if (rule.node_types && (!nodeType || !rule.node_types.includes(nodeType))) return undefined;
  return rule.rule_id;
}

export function getMetricSubtitle(
  rule: DetectionRuleResponse | undefined,
  evalResult: { status: string; label: string },
  nodeType: string | undefined,
  unit: string
): string {
  if (evalResult.status === 'unknown') return 'Insufficient telemetry';
  if (!rule) return 'Rule unavailable';
  if (!rule.enabled) return 'Rule inactive';
  if (rule.node_types && (!nodeType || !rule.node_types.includes(nodeType))) {
    return `N/A: Applies to ${rule.node_types.join(', ')}`;
  }
  return `${rule.rule_id} (${rule.operator} ${rule.threshold} ${unit})`.trim();
}

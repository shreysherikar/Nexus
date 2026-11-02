import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Play,
  RotateCcw,
  Zap,
  ZapOff,
  Activity,
  Layers,
  Radio,
  WifiOff,
} from 'lucide-react';
import { apiClient } from '@/api/client';
import {
  ActiveScenarioResponse,
  FaultScenarioInfo,
  TelemetryGenerateStepResponse,
} from '@/types/api';
import { useWebSocketSubscription } from '@/websocket/useWebSocket';
import { WsEventType } from '@/types/websocket';

export interface FaultInjectionPanelProps {
  onSimulationStepTriggered?: (res: TelemetryGenerateStepResponse) => void;
  className?: string;
}

export const FaultInjectionPanel: React.FC<FaultInjectionPanelProps> = ({
  onSimulationStepTriggered,
  className = '',
}) => {
  const [scenarios, setScenarios] = useState<FaultScenarioInfo[]>([]);
  const [activeScenario, setActiveScenario] = useState<ActiveScenarioResponse | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [generatingStep, setGeneratingStep] = useState(false);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const fetchFaultData = useCallback(async () => {
    try {
      const [listRes, activeRes] = await Promise.all([
        apiClient.getFaultScenarios(),
        apiClient.getActiveFaultScenario(),
      ]);
      setScenarios(listRes.items);
      setActiveScenario(activeRes);
    } catch (err: unknown) {
      console.error('[FaultPanel] Failed to fetch fault state:', err);
    }
  }, []);

  useEffect(() => {
    fetchFaultData();
  }, [fetchFaultData]);

  // Real-time updates via WebSocket
  useWebSocketSubscription(WsEventType.FAULT_STATUS_CHANGED, () => {
    fetchFaultData();
  });

  const handleActivate = async (scenarioId: string) => {
    setActionLoading(true);
    setFeedback(null);
    try {
      const res = await apiClient.activateFaultScenario(scenarioId);
      setActiveScenario(res.active_scenario);
      setFeedback({ type: 'success', message: res.message });
      await fetchFaultData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to activate fault scenario';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeactivate = async () => {
    setActionLoading(true);
    setFeedback(null);
    try {
      const res = await apiClient.deactivateFaultScenario();
      setActiveScenario(res.active_scenario);
      setFeedback({ type: 'success', message: res.message });
      await fetchFaultData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to deactivate fault scenario';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setActionLoading(false);
    }
  };

  const handleTriggerStep = async () => {
    setGeneratingStep(true);
    setFeedback(null);
    try {
      const res = await apiClient.generateTelemetryStep();
      setFeedback({
        type: 'success',
        message: `Simulation step generated (${res.generated_count} node snapshots). Telemetry and detection evaluated.`,
      });
      if (onSimulationStepTriggered) {
        onSimulationStepTriggered(res);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Telemetry generation failed';
      setFeedback({ type: 'error', message: msg });
    } finally {
      setGeneratingStep(false);
    }
  };

  const getFaultIcon = (faultType: string) => {
    switch (faultType) {
      case 'RADIO_INTERFERENCE':
        return <Radio className="w-4 h-4 text-amber-400" />;
      case 'CELL_OUTAGE':
        return <WifiOff className="w-4 h-4 text-rose-400" />;
      case 'BACKHAUL_FAILURE':
        return <Layers className="w-4 h-4 text-purple-400" />;
      case 'SITE_POWER_FAILURE':
        return <ZapOff className="w-4 h-4 text-rose-500" />;
      case 'CELL_CONGESTION':
        return <Activity className="w-4 h-4 text-amber-300" />;
      default:
        return <AlertTriangle className="w-4 h-4 text-blue-400" />;
    }
  };

  return (
    <div
      className={`bg-noc-surface border border-noc-border rounded-lg p-5 shadow-sm space-y-4 ${className}`}
      data-testid="fault-injection-panel"
    >
      {/* Header: Title and Active State Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-noc-border/60">
        <div>
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-amber-400" />
            <h2 className="text-sm font-mono font-bold text-noc-text-primary uppercase tracking-wider">
              Fault Injection & Controlled Simulation
            </h2>
          </div>
          <p className="text-xs text-noc-text-secondary mt-1">
            Inject deterministic telecom failure scenarios into the synthetic telemetry stream. Ground-truth root cause remains strictly isolated from downstream detection.
          </p>
        </div>

        {/* Global Controls: Step Trigger & Deactivate */}
        <div className="flex items-center gap-2 flex-wrap">
          {activeScenario?.active && (
            <button
              type="button"
              onClick={handleDeactivate}
              disabled={actionLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono font-semibold bg-rose-950/80 hover:bg-rose-900 border border-rose-700/60 text-rose-200 transition-colors"
              title="Deactivate injected fault and restore network to nominal conditions"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Deactivate Fault</span>
            </button>
          )}

          <button
            type="button"
            onClick={handleTriggerStep}
            disabled={generatingStep}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded text-xs font-mono font-semibold bg-blue-600 hover:bg-blue-500 text-white shadow-sm transition-colors disabled:opacity-50"
            title="Explicit operator simulation trigger: generates 1 cycle of telemetry and runs anomaly detection"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>{generatingStep ? 'Stepping...' : 'Trigger Simulation Step'}</span>
          </button>
        </div>
      </div>

      {/* Active State Pill */}
      <div
        className={`px-3 py-2 rounded border flex items-center justify-between gap-3 text-xs font-mono ${
          activeScenario?.active
            ? 'bg-amber-950/40 border-amber-600/50 text-amber-200'
            : 'bg-emerald-950/30 border-emerald-700/40 text-emerald-300'
        }`}
      >
        <div className="flex items-center gap-2">
          {activeScenario?.active ? (
            <AlertTriangle className="w-4 h-4 text-amber-400 animate-pulse" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          )}
          <span>
            {activeScenario?.active ? (
              <>
                <strong className="font-bold text-amber-300">FAULT ACTIVE:</strong>{' '}
                {activeScenario.name} &bull; Target: {activeScenario.faults[0]?.target_id} &bull; Blast Radius: [
                {activeScenario.faults[0]?.affected_nodes.join(', ')}]
              </>
            ) : (
              <>
                <strong className="font-bold text-emerald-300">NETWORK NOMINAL:</strong> Baseline synthetic telemetry, zero injected impairments.
              </>
            )}
          </span>
        </div>
        {activeScenario?.active && (
          <span className="px-2 py-0.5 rounded bg-amber-500/20 border border-amber-500/40 text-[10px] uppercase font-bold text-amber-300">
            Impairment In Effect
          </span>
        )}
      </div>

      {/* Action Notification */}
      {feedback && (
        <div
          className={`px-3 py-2 rounded text-xs font-mono border ${
            feedback.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-600/50 text-emerald-200'
              : 'bg-rose-950/40 border-rose-600/50 text-rose-200'
          }`}
        >
          {feedback.message}
        </div>
      )}

      {/* Scenario Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 pt-1">
        {scenarios.map((sc) => {
          const isCurrentActive = activeScenario?.active && activeScenario.scenario_key === sc.id;
          return (
            <div
              key={sc.id}
              className={`p-3 rounded border flex flex-col justify-between transition-all ${
                isCurrentActive
                  ? 'bg-amber-950/30 border-amber-500/80 ring-1 ring-amber-500/50 shadow-md'
                  : 'bg-noc-canvas border-noc-border hover:border-noc-border/90'
              }`}
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5">
                    {getFaultIcon(sc.fault_type)}
                    <span className="text-xs font-bold font-mono text-noc-text-primary">
                      {sc.name}
                    </span>
                  </div>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-noc-surface border border-noc-border text-noc-text-secondary">
                    {sc.target_id}
                  </span>
                </div>

                <p className="text-[11px] text-noc-text-secondary line-clamp-2 mb-2 leading-relaxed">
                  {sc.description}
                </p>

                <div className="text-[10px] font-mono text-noc-text-muted flex items-center justify-between border-t border-noc-border/40 pt-1.5 mb-2">
                  <span>Type: {sc.fault_type}</span>
                  <span>Severity: {sc.severity}</span>
                </div>
              </div>

              <div className="mt-1">
                {isCurrentActive ? (
                  <button
                    type="button"
                    onClick={handleDeactivate}
                    disabled={actionLoading}
                    className="w-full py-1 px-2 rounded text-xs font-mono font-semibold bg-rose-900/60 hover:bg-rose-900 border border-rose-700/50 text-rose-200 transition-colors"
                  >
                    Deactivate Scenario
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleActivate(sc.id)}
                    disabled={actionLoading || generatingStep}
                    className="w-full py-1 px-2 rounded text-xs font-mono font-semibold bg-noc-surface hover:bg-noc-base border border-noc-border hover:border-noc-border/80 text-noc-text-primary transition-colors disabled:opacity-50"
                  >
                    Activate Scenario
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

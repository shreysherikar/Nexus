#!/usr/bin/env python3
"""CLI runner to reproduce the six-scenario evaluation benchmark.

Replays all six reference telecom fault scenarios through the end-to-end evaluation
pipeline (Simulation -> Detection -> Correlation -> RCA -> Benchmark Evaluation)
using deterministic seed 42 and 30-step simulation runs.

Calls existing evaluation implementation from `nexus.evaluation.scenario_replay`
without duplicating evaluation or metric calculation logic.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys

# Ensure src/ is on sys.path when executed directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from nexus.correlation.engine import AlarmCorrelationEngine
from nexus.detection.engine import AnomalyDetectionEngine
from nexus.evaluation.scenario_replay import ScenarioReplayEvaluator
from nexus.fault.scenarios import build_reference_scenarios
from nexus.rca.engine import RootCauseAnalysisEngine
from nexus.telemetry.generator import SyntheticTelemetryGenerator
from nexus.topology.builder import build_simulated_network
from nexus.transport.builder import build_reference_transport_network


def run_benchmark(
    seed: int = 42,
    steps: int = 30,
    grace_period_seconds: float = 120.0,
    base_time: datetime | None = None,
) -> dict:
    """Run full pipeline evaluation across all six reference fault scenarios.

    Args:
        seed: Random seed for synthetic telemetry generator (default: 42).
        steps: Number of 1-minute telemetry steps per scenario (default: 30).
        grace_period_seconds: Post-fault matching grace period (default: 120.0).
        base_time: Base timestamp for simulation (default: 2026-01-01 12:00:00 UTC).

    Returns:
        Structured dictionary containing metadata, aggregate metrics, and per-scenario metrics.
    """
    if base_time is None:
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    net = build_simulated_network()
    transport = build_reference_transport_network(net)
    node_types = {n.node_id: n.node_type for n in net.all_nodes()}
    scenarios = build_reference_scenarios(net, transport, base_time=base_time)

    scenario_keys = [
        "cell_outage",
        "backhaul_failure",
        "radio_interference",
        "cell_congestion",
        "site_power_failure",
        "core_router_failure",
    ]

    per_scenario_results = {}

    total_injected_faults = 0
    total_detected_faults = 0
    total_undetected_faults = 0
    total_alarms_raised = 0
    total_tp_alarms = 0
    total_fp_alarms = 0
    total_diagnosed_faults = 0
    total_correct_cause_count = 0
    total_correct_target_count = 0
    total_both_correct_count = 0
    total_unknown_count = 0
    total_misdiagnosed_count = 0
    total_groups_formed = 0
    all_detection_delays = []

    for key in scenario_keys:
        fault_engine = scenarios[key]
        ground_truth = fault_engine.get_ground_truth()
        gt_record = ground_truth[0]

        # 1. Deterministic telemetry generation with fault injection
        gen = SyntheticTelemetryGenerator(net, seed=seed)
        all_snapshots = []
        for i in range(steps):
            step_time = base_time + timedelta(minutes=i)
            base_snaps = gen.generate_step(timestamp=step_time)
            effective_snaps = fault_engine.apply_faults(base_snaps, timestamp=step_time)
            all_snapshots.extend(effective_snaps)

        # 2. Pipeline execution via existing ScenarioReplayEvaluator
        detection_engine = AnomalyDetectionEngine()
        correlation_engine = AlarmCorrelationEngine(topology=net, transport=transport)
        rca_engine = RootCauseAnalysisEngine(topology=net, transport=transport)
        evaluator = ScenarioReplayEvaluator(engine=detection_engine)

        batch_result, det_report, corr_result, rca_results, rca_report = evaluator.replay_and_evaluate_pipeline(
            snapshots=all_snapshots,
            ground_truth=ground_truth,
            topology=net,
            transport=transport,
            node_types=node_types,
            grace_period_seconds=grace_period_seconds,
            correlation_engine=correlation_engine,
            rca_engine=rca_engine,
        )

        gt_match = rca_report.fault_matches[0]

        scenario_data = {
            "scenario_key": key,
            "fault_type": gt_record.fault_type.value if hasattr(gt_record.fault_type, "value") else str(gt_record.fault_type),
            "target_id": gt_record.target_id,
            "affected_node_ids": list(gt_record.affected_node_ids),
            "total_faults": det_report.total_faults,
            "detected_faults": det_report.detected_faults,
            "undetected_faults": det_report.undetected_faults,
            "total_alarms": det_report.total_alarms,
            "true_positives": det_report.true_positive_alarms,
            "false_positives": det_report.false_positive_alarms,
            "false_negatives": det_report.undetected_faults,
            "true_negatives": "NOT_CALCULATED_OR_UNDEFINED",
            "alarm_precision": round(det_report.alarm_precision, 4),
            "fault_recall": round(det_report.fault_recall, 4),
            "hybrid_f1_score": round(det_report.hybrid_f1_score, 4),
            "false_positive_rate": "NOT_CALCULATED_OR_UNDEFINED",
            "mean_time_to_detect_seconds": det_report.mean_time_to_detect_seconds,
            "correlation_groups_formed": corr_result.total_groups_formed,
            "alarm_reduction_ratio": round(corr_result.reduction_ratio, 4),
            "rca_diagnosed": rca_report.diagnosed_faults,
            "rca_cause_correct": gt_match.cause_correct,
            "rca_target_correct": gt_match.target_correct,
            "rca_both_correct": gt_match.both_correct,
            "rca_diagnosed_cause": gt_match.diagnosed_cause_type,
            "rca_diagnosed_target": gt_match.diagnosed_target_id,
            "rca_confidence": gt_match.confidence_score,
            "rca_top_1_cause_accuracy": round(rca_report.top_1_cause_accuracy, 4),
            "rca_target_accuracy": round(rca_report.target_accuracy, 4),
            "rca_both_accuracy": round(rca_report.both_accuracy, 4),
        }
        per_scenario_results[key] = scenario_data

        total_injected_faults += det_report.total_faults
        total_detected_faults += det_report.detected_faults
        total_undetected_faults += det_report.undetected_faults
        total_alarms_raised += det_report.total_alarms
        total_tp_alarms += det_report.true_positive_alarms
        total_fp_alarms += det_report.false_positive_alarms
        total_diagnosed_faults += rca_report.diagnosed_faults
        total_correct_cause_count += rca_report.correct_cause_count
        total_correct_target_count += rca_report.correct_target_count
        total_both_correct_count += rca_report.correct_both_count
        total_unknown_count += rca_report.unknown_count
        total_misdiagnosed_count += rca_report.misdiagnosed_count
        total_groups_formed += corr_result.total_groups_formed
        if det_report.mean_time_to_detect_seconds is not None:
            all_detection_delays.append(det_report.mean_time_to_detect_seconds)

    micro_alarm_precision = total_tp_alarms / total_alarms_raised if total_alarms_raised > 0 else 0.0
    micro_fault_recall = total_detected_faults / total_injected_faults if total_injected_faults > 0 else 0.0
    micro_hybrid_f1 = (
        (2 * micro_alarm_precision * micro_fault_recall) / (micro_alarm_precision + micro_fault_recall)
        if (micro_alarm_precision + micro_fault_recall) > 0
        else 0.0
    )
    avg_mttd = sum(all_detection_delays) / len(all_detection_delays) if all_detection_delays else 0.0
    macro_alarm_reduction = (
        (total_alarms_raised - total_groups_formed) / total_alarms_raised
        if total_alarms_raised > 0
        else 0.0
    )

    rca_top_1_cause_acc = total_correct_cause_count / total_injected_faults if total_injected_faults > 0 else 0.0
    rca_target_acc = total_correct_target_count / total_injected_faults if total_injected_faults > 0 else 0.0
    rca_both_acc = total_both_correct_count / total_injected_faults if total_injected_faults > 0 else 0.0

    return {
        "metadata": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "random_seed": seed,
            "simulation_steps_per_scenario": steps,
            "grace_period_seconds": grace_period_seconds,
            "scenarios_evaluated_count": len(scenario_keys),
            "scenarios_list": scenario_keys,
        },
        "aggregate_metrics": {
            "total_scenarios": len(scenario_keys),
            "total_ground_truth_faults": total_injected_faults,
            "total_detected_faults": total_detected_faults,
            "total_undetected_faults": total_undetected_faults,
            "total_alarms_raised": total_alarms_raised,
            "total_true_positive_alarms": total_tp_alarms,
            "total_false_positive_alarms": total_fp_alarms,
            "total_false_negatives": total_undetected_faults,
            "total_true_negatives": "NOT_CALCULATED_OR_UNDEFINED",
            "false_positive_rate": "NOT_CALCULATED_OR_UNDEFINED",
            "micro_alarm_precision": round(micro_alarm_precision, 4),
            "micro_fault_recall": round(micro_fault_recall, 4),
            "micro_hybrid_f1_score": round(micro_hybrid_f1, 4),
            "mean_time_to_detect_seconds": round(avg_mttd, 2),
            "total_correlation_groups_formed": total_groups_formed,
            "aggregate_alarm_reduction_ratio": round(macro_alarm_reduction, 4),
            "rca_diagnosed_faults": total_diagnosed_faults,
            "rca_top_1_cause_accuracy": round(rca_top_1_cause_acc, 4),
            "rca_target_accuracy": round(rca_target_acc, 4),
            "rca_both_accuracy": round(rca_both_acc, 4),
            "rca_unknown_count": total_unknown_count,
            "rca_misdiagnosed_count": total_misdiagnosed_count,
        },
        "per_scenario_results": per_scenario_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NEXUS Six-Scenario Evaluation Benchmark Runner"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic telemetry generation (default: 42)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=30,
        help="Number of simulation steps per scenario (default: 30)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Optional path to write raw JSON benchmark results",
    )
    args = parser.parse_args()

    results = run_benchmark(seed=args.seed, steps=args.steps)
    json_output = json.dumps(results, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_output, encoding="utf-8")
        print(f"Benchmark results written to {args.output}")

    print(json.dumps(results["aggregate_metrics"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

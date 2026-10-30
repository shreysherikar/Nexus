"""Evaluator module calculating precision, recall, F1, and MTTD against ground truth."""

from datetime import datetime, timedelta
import math
from typing import Optional, Sequence

from nexus.detection.models import Alarm
from nexus.evaluation.models import EvaluationReport, FaultDetectionMatch
from nexus.fault.models import GroundTruthRecord


def evaluate_detections(
    ground_truth: Sequence[GroundTruthRecord],
    alarms: Sequence[Alarm],
    grace_period_seconds: float = 60.0,
) -> EvaluationReport:
    """Benchmark detection alarms against injected ground-truth fault events.

    Matching Policy:
    1. Alarm Deduplication:
       Alarms are deduplicated by alarm_id before evaluation to prevent duplicate counting.
    2. Fault Matching:
       An alarm is eligible to match a fault if:
       - The alarm's target node_id is within the fault's affected_node_ids.
       - The alarm was first observed during the fault or within grace_period_seconds of its end:
         fault.start_time <= alarm.first_seen <= fault.end_time + grace_period.
    3. Overlapping Faults:
       If multiple faults overlap in time and share affected nodes, an alarm on a shared node
       within the overlap window matches all overlapping faults it is eligible for (incrementing
       detected status for each). In alarm counting, the unique alarm is counted once as a True Positive.
    4. Metrics:
       - alarm_precision: Unique true positive alarms / total unique alarms.
       - fault_recall: Detected faults / total faults.
       - hybrid_f1_score: Harmonic mean of alarm_precision and fault_recall.
       - MTTD (Mean Time to Detect): Latency from fault.start_time to the earliest matching alarm
         for that fault, averaged across all detected faults.

    Args:
        ground_truth: Sequence of precomputed GroundTruthRecord instances from injected faults.
        alarms: Sequence of Alarm instances produced by the AnomalyDetectionEngine.
        grace_period_seconds: Maximum seconds after fault end_time during which delayed alarms match.

    Returns:
        Structured EvaluationReport with precision, recall, F1, MTTD, and detailed matches.
    """
    grace_delta = timedelta(seconds=max(0.0, float(grace_period_seconds)))

    # Deduplicate alarms by unique alarm_id
    unique_alarms_map: dict[str, Alarm] = {}
    for a in alarms:
        if not isinstance(a, Alarm):
            raise TypeError(f"Expected Alarm instance, got {type(a).__name__}")
        if a.alarm_id not in unique_alarms_map:
            unique_alarms_map[a.alarm_id] = a
    unique_alarms = list(unique_alarms_map.values())

    fault_matches: list[FaultDetectionMatch] = []
    matched_alarm_ids: set[str] = set()
    detection_delays: list[float] = []

    for gt in ground_truth:
        affected_set = set(gt.affected_node_ids)
        window_start = gt.start_time
        window_end = gt.end_time + grace_delta

        # Find eligible alarms for this ground-truth fault
        eligible_alarms: list[Alarm] = []
        for alarm in unique_alarms:
            if alarm.node_id in affected_set:
                if window_start <= alarm.first_seen <= window_end:
                    eligible_alarms.append(alarm)
                    matched_alarm_ids.add(alarm.alarm_id)

        if eligible_alarms:
            # Sort eligible alarms by first_seen to calculate earliest detection delay
            earliest_alarm = min(eligible_alarms, key=lambda a: a.first_seen)
            delay = max(0.0, (earliest_alarm.first_seen - gt.start_time).total_seconds())
            detection_delays.append(delay)

            fault_matches.append(
                FaultDetectionMatch(
                    fault_id=gt.fault_id,
                    fault_type=gt.fault_type.value if hasattr(gt.fault_type, "value") else str(gt.fault_type),
                    target_id=gt.target_id,
                    start_time=gt.start_time,
                    end_time=gt.end_time,
                    affected_node_ids=gt.affected_node_ids,
                    detected=True,
                    matching_alarm_ids=tuple(sorted(a.alarm_id for a in eligible_alarms)),
                    detection_delay_seconds=round(delay, 2),
                )
            )
        else:
            fault_matches.append(
                FaultDetectionMatch(
                    fault_id=gt.fault_id,
                    fault_type=gt.fault_type.value if hasattr(gt.fault_type, "value") else str(gt.fault_type),
                    target_id=gt.target_id,
                    start_time=gt.start_time,
                    end_time=gt.end_time,
                    affected_node_ids=gt.affected_node_ids,
                    detected=False,
                    matching_alarm_ids=(),
                    detection_delay_seconds=None,
                )
            )

    total_faults = len(ground_truth)
    detected_faults = sum(1 for m in fault_matches if m.detected)
    undetected_faults = total_faults - detected_faults

    total_alarms = len(unique_alarms)
    tp_alarms = len(matched_alarm_ids)
    fp_alarms = total_alarms - tp_alarms

    unmatched_alarm_ids = tuple(
        sorted(a.alarm_id for a in unique_alarms if a.alarm_id not in matched_alarm_ids)
    )

    # Metric computations with documented zero-denominator edge-case handling:
    # 1. Alarm Precision: proportion of unique alarms that were true positives
    if total_alarms == 0:
        alarm_precision = 1.0 if total_faults == 0 else 0.0
    else:
        alarm_precision = round(tp_alarms / total_alarms, 4)

    # 2. Fault Recall: proportion of injected faults that were detected
    if total_faults == 0:
        fault_recall = 1.0
    else:
        fault_recall = round(detected_faults / total_faults, 4)

    # 3. Hybrid F1 score: harmonic mean of alarm_precision and fault_recall
    if (alarm_precision + fault_recall) > 0.0:
        hybrid_f1 = round(2.0 * (alarm_precision * fault_recall) / (alarm_precision + fault_recall), 4)
    else:
        hybrid_f1 = 0.0

    # 4. Mean Time to Detect (MTTD)
    # Calculated per detected fault (earliest matching alarm for that fault), averaged across detected faults.
    if detection_delays:
        mttd = round(sum(detection_delays) / len(detection_delays), 2)
    else:
        mttd = None

    return EvaluationReport(
        total_faults=total_faults,
        detected_faults=detected_faults,
        undetected_faults=undetected_faults,
        total_alarms=total_alarms,
        true_positive_alarms=tp_alarms,
        false_positive_alarms=fp_alarms,
        alarm_precision=alarm_precision,
        fault_recall=fault_recall,
        hybrid_f1_score=hybrid_f1,
        mean_time_to_detect_seconds=mttd,
        fault_matches=tuple(fault_matches),
        unmatched_alarm_ids=unmatched_alarm_ids,
    )

"""Evaluator module calculating precision, recall, F1, and MTTD against ground truth."""

from datetime import datetime, timedelta
import math
from typing import Optional, Sequence

from nexus.correlation.models import CorrelationResult
from nexus.detection.models import Alarm
from nexus.evaluation.models import (
    EvaluationReport,
    FaultDetectionMatch,
    RCAEvaluationReport,
    RCAGroundTruthMatch,
)
from nexus.fault.models import GroundTruthRecord
from nexus.rca.models import RCAResult, TargetType
from nexus.transport.network import TransportNetwork


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


def evaluate_rca(
    ground_truth: Sequence[GroundTruthRecord],
    rca_results: Sequence[RCAResult],
    correlation_result: Optional[CorrelationResult] = None,
    grace_period_seconds: float = 60.0,
    transport: Optional[TransportNetwork] = None,
) -> RCAEvaluationReport:
    """Benchmark RCA diagnoses against injected ground-truth fault events.

    Candidate Selection Policy:
    Candidates are matched using pure spatio-temporal affinity without inspecting diagnostic correctness:
    1. Spatial Overlap: Count of group nodes intersecting the fault's affected node set (higher is better).
    2. Temporal Proximity: Minimal absolute time delta to the fault start time (-abs(t - start) is better).
    3. Symptom Density: Total alarm count within the candidate group (higher is better).
    4. Deterministic Tie-Breakers: Group onset timestamp and unique group identifier.

    Target Matching Policy for Node and Transport-Link Hypotheses:
    1. Exact Match: If diagnosed target ID matches expected target ID exactly, target is correct.
    2. Unlike Identifiers (Link Diagnosis for Node Target): If the hypothesis diagnoses a transport link
       while ground truth targets a node:
       - If transport network is provided and contains the diagnosed link, the link is correct if its
         downstream endpoint equals the expected target node (the link directly feeds the node).
       - If the link feeds a different node, target is incorrect.
       - If transport network is not provided, target correctness is represented as not independently
         verifiable (target_correct=None, target_verifiable=False) rather than fabricating a match.
    3. Unlike Identifiers (Node Diagnosis for Link Target): If the hypothesis diagnoses a node while
       ground truth targets a transport link, the node target does not match the link (target_correct=False).
    4. Direct Mismatches: If both are nodes or both are links and identifiers differ, target_correct=False.

    Args:
        ground_truth: Sequence of precomputed GroundTruthRecord instances.
        rca_results: Sequence of RCAResult instances produced by RootCauseAnalysisEngine.
        correlation_result: Optional CorrelationResult containing groups and reduction stats.
        grace_period_seconds: Maximum seconds after fault end_time during which diagnoses match.
        transport: Optional TransportNetwork for resolving physical transport link endpoints.

    Returns:
        Structured RCAEvaluationReport summarizing correlation and diagnostic accuracy.
    """
    if isinstance(ground_truth, (str, bytes)) or not isinstance(ground_truth, Sequence):
        raise TypeError("ground_truth must be a Sequence of GroundTruthRecord")
    for gt in ground_truth:
        if not isinstance(gt, GroundTruthRecord):
            raise TypeError(f"Expected GroundTruthRecord instance, got {type(gt).__name__}")

    if isinstance(rca_results, (str, bytes)) or not isinstance(rca_results, Sequence):
        raise TypeError("rca_results must be a Sequence of RCAResult")
    for rca in rca_results:
        if not isinstance(rca, RCAResult):
            raise TypeError(f"Expected RCAResult instance, got {type(rca).__name__}")

    if correlation_result is not None and not isinstance(correlation_result, CorrelationResult):
        raise TypeError(f"Expected CorrelationResult or None, got {type(correlation_result).__name__}")

    if transport is not None and not isinstance(transport, TransportNetwork):
        raise TypeError(f"Expected TransportNetwork or None, got {type(transport).__name__}")

    grace_delta = timedelta(seconds=max(0.0, float(grace_period_seconds)))

    group_by_id = {}
    if correlation_result is not None:
        for g in correlation_result.groups:
            group_by_id[g.group_id] = g

    fault_matches: list[RCAGroundTruthMatch] = []
    matched_group_ids: set[str] = set()

    for gt in ground_truth:
        affected_set = set(gt.affected_node_ids)
        affected_set.add(gt.target_id)
        window_start = gt.start_time
        window_end = gt.end_time + grace_delta
        expected_cause = gt.fault_type.value if hasattr(gt.fault_type, "value") else str(gt.fault_type)
        expected_target = gt.target_id

        # Find eligible RCA results for this ground-truth fault.
        candidate_matches: list[tuple[tuple[int, float, int, float, str], RCAResult, str]] = []

        for rca in rca_results:
            group = group_by_id.get(rca.group_id)
            is_eligible = False
            overlap_node_count = 0
            alarm_count = 0
            group_start_ts = rca.analysis_timestamp

            if group is not None:
                alarm_count = group.alarm_count
                group_start_ts = group.time_window_start
                temp_overlap = (group.time_window_start <= window_end) and (group.time_window_end >= window_start - grace_delta)
                if temp_overlap:
                    common_nodes = affected_set.intersection(group.node_ids)
                    overlap_node_count = len(common_nodes)
                    anchor_match = (
                        group.anchor_node_id in affected_set or group.anchor_node_id == expected_target
                    )
                    if overlap_node_count > 0 or anchor_match:
                        is_eligible = True
            else:
                temp_overlap = (window_start - grace_delta <= rca.analysis_timestamp <= window_end)
                if temp_overlap:
                    # When no correlation group is provided, check if primary hypothesis targets affected set
                    target_match = False
                    if rca.primary_hypothesis is not None:
                        t_id = rca.primary_hypothesis.target_id
                        if t_id in affected_set or t_id == expected_target:
                            target_match = True
                        elif transport is not None and transport.has_link(t_id):
                            link = transport.get_link(t_id)
                            if link.downstream_node_id in affected_set or link.downstream_node_id == expected_target:
                                target_match = True
                        elif transport is not None and transport.has_link(expected_target):
                            link = transport.get_link(expected_target)
                            if link.downstream_node_id == t_id or t_id in affected_set:
                                target_match = True
                        elif transport is None and (
                            rca.primary_hypothesis.target_type == TargetType.TRANSPORT_LINK
                            or t_id.startswith("LINK-")
                            or expected_target.startswith("LINK-")
                        ):
                            target_match = (
                                any(aff in t_id for aff in affected_set)
                                or (expected_target in t_id)
                                or (t_id in expected_target)
                            )
                    if target_match:
                        is_eligible = True
                        overlap_node_count = 1

            if is_eligible:
                time_dist = abs((group_start_ts - window_start).total_seconds())
                ts_neg = -group_start_ts.timestamp()
                score_tuple = (overlap_node_count, -time_dist, alarm_count, ts_neg, rca.group_id)
                candidate_matches.append((score_tuple, rca, rca.group_id))

        if candidate_matches:
            candidate_matches.sort(key=lambda item: item[0], reverse=True)
            best_score, best_rca, best_group_id = candidate_matches[0]
            matched_group_ids.add(best_group_id)

            primary = best_rca.primary_hypothesis
            if primary is not None:
                diag_cause = primary.cause_type.value
                diag_target = primary.target_id
                diag_conf = primary.confidence_score
                is_unk = (diag_cause == "UNKNOWN")
            else:
                diag_cause = None
                diag_target = None
                diag_conf = None
                is_unk = True

            c_correct = (not is_unk) and (diag_cause == expected_cause)

            t_correct: Optional[bool] = None
            t_verifiable: bool = True

            if is_unk or diag_target is None:
                t_correct = False
            elif diag_target == expected_target:
                t_correct = True
            else:
                # Handle unlike identifiers (node vs transport link)
                is_diag_link = (primary is not None and primary.target_type == TargetType.TRANSPORT_LINK) or diag_target.startswith("LINK-")
                is_expected_link = expected_target.startswith("LINK-")

                if is_diag_link and not is_expected_link:
                    # Diagnosed target is a link; expected target is a node
                    if transport is not None:
                        if transport.has_link(diag_target):
                            link = transport.get_link(diag_target)
                            # Link is correct if it directly serves the expected target node
                            t_correct = (link.downstream_node_id == expected_target)
                        else:
                            t_correct = False
                    else:
                        # Insufficient ground-truth / transport information to verify link endpoints
                        t_correct = None
                        t_verifiable = False
                elif not is_diag_link and is_expected_link:
                    # Diagnosed target is a node; expected target is a link
                    if transport is not None:
                        t_correct = False
                    else:
                        t_correct = None
                        t_verifiable = False
                else:
                    # Both are nodes or both are links, but IDs do not match
                    t_correct = False

            b_correct = bool(c_correct and (t_correct is True))

            fault_matches.append(
                RCAGroundTruthMatch(
                    fault_id=gt.fault_id,
                    fault_type=expected_cause,
                    target_id=expected_target,
                    matched_group_id=best_group_id,
                    diagnosed_cause_type=diag_cause,
                    diagnosed_target_id=diag_target,
                    confidence_score=diag_conf,
                    cause_correct=c_correct,
                    target_correct=t_correct,
                    both_correct=b_correct,
                    is_unknown=is_unk,
                    target_verifiable=t_verifiable,
                )
            )
        else:
            fault_matches.append(
                RCAGroundTruthMatch(
                    fault_id=gt.fault_id,
                    fault_type=expected_cause,
                    target_id=expected_target,
                    matched_group_id=None,
                    diagnosed_cause_type=None,
                    diagnosed_target_id=None,
                    confidence_score=None,
                    cause_correct=False,
                    target_correct=False,
                    both_correct=False,
                    is_unknown=True,
                    target_verifiable=True,
                )
            )

    total_faults = len(ground_truth)
    correct_cause_count = sum(1 for m in fault_matches if m.cause_correct)
    correct_target_count = sum(1 for m in fault_matches if m.target_correct is True)
    correct_both_count = sum(1 for m in fault_matches if m.both_correct)
    unknown_count = sum(1 for m in fault_matches if m.is_unknown)
    unevaluable_target_count = sum(1 for m in fault_matches if not m.target_verifiable)
    diagnosed_faults = total_faults - unknown_count
    misdiagnosed_count = sum(1 for m in fault_matches if (not m.is_unknown) and (not m.cause_correct))

    if total_faults == 0:
        top_1_cause_accuracy = 1.0
        target_accuracy = 1.0
        both_accuracy = 1.0
        diagnosis_coverage = 1.0
    else:
        top_1_cause_accuracy = round(correct_cause_count / total_faults, 4)
        target_accuracy = round(correct_target_count / total_faults, 4)
        both_accuracy = round(correct_both_count / total_faults, 4)
        diagnosis_coverage = round(diagnosed_faults / total_faults, 4)

    if correlation_result is not None:
        total_alarms = correlation_result.total_alarms_processed
        total_groups = correlation_result.total_groups_formed
        alarm_reduction_ratio = correlation_result.reduction_ratio
    else:
        total_alarms = 0
        total_groups = len(rca_results)
        alarm_reduction_ratio = 0.0

    all_evaluated_groups = set()
    if correlation_result is not None:
        all_evaluated_groups.update(g.group_id for g in correlation_result.groups)
    all_evaluated_groups.update(r.group_id for r in rca_results)

    unmatched_group_ids = tuple(sorted(all_evaluated_groups - matched_group_ids))

    return RCAEvaluationReport(
        total_faults=total_faults,
        diagnosed_faults=diagnosed_faults,
        correct_cause_count=correct_cause_count,
        correct_target_count=correct_target_count,
        correct_both_count=correct_both_count,
        unknown_count=unknown_count,
        misdiagnosed_count=misdiagnosed_count,
        top_1_cause_accuracy=top_1_cause_accuracy,
        target_accuracy=target_accuracy,
        both_accuracy=both_accuracy,
        diagnosis_coverage=diagnosis_coverage,
        total_alarms=total_alarms,
        total_groups=total_groups,
        alarm_reduction_ratio=alarm_reduction_ratio,
        fault_matches=tuple(fault_matches),
        unmatched_group_ids=unmatched_group_ids,
        unevaluable_target_count=unevaluable_target_count,
    )

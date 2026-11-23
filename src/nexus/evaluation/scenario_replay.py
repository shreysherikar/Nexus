"""Scenario replay and post-hoc evaluation coordinator."""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from nexus.correlation.engine import AlarmCorrelationEngine
from nexus.correlation.models import CorrelationResult
from nexus.detection.engine import AnomalyDetectionEngine, DetectionBatchResult
from nexus.evaluation.evaluator import evaluate_detections, evaluate_rca
from nexus.evaluation.models import EvaluationReport, RCAEvaluationReport
from nexus.fault.models import GroundTruthRecord
from nexus.rca.engine import RootCauseAnalysisEngine
from nexus.rca.models import RCAResult
from nexus.telemetry.models import KPISnapshot
from nexus.topology.enums import NodeType
from nexus.topology.topology import Topology
from nexus.transport.network import TransportNetwork


class ScenarioReplayEvaluator:
    """Feeds synthetic telemetry snapshots into a detection engine and evaluates output against ground truth.

    Crucially, the detection engine receives ONLY telemetry snapshots. Ground-truth records are held
    strictly outside the detection process and used exclusively for post-hoc validation.
    """

    def __init__(self, engine: Optional[AnomalyDetectionEngine] = None) -> None:
        self._engine = engine if engine is not None else AnomalyDetectionEngine()

    @property
    def engine(self) -> AnomalyDetectionEngine:
        return self._engine

    def replay_and_evaluate(
        self,
        snapshots: Sequence[KPISnapshot],
        ground_truth: Sequence[GroundTruthRecord],
        node_types: Optional[Mapping[str, Optional[NodeType]]] = None,
        grace_period_seconds: float = 60.0,
    ) -> tuple[DetectionBatchResult, EvaluationReport]:
        """Replay snapshots through the detection engine and evaluate resulting alarms against ground truth.

        Args:
            snapshots: Telemetry time-series snapshots to process.
            ground_truth: Pre-recorded ground-truth fault impact records.
            node_types: Optional node_id to NodeType mapping for rule filtering.
            grace_period_seconds: Post-fault grace interval in seconds for detection matching.

        Returns:
            Tuple of (DetectionBatchResult, EvaluationReport).
        """
        # 1. Feed ONLY snapshots to detection engine
        batch_result = self._engine.process_batch(snapshots, node_types=node_types)

        # 2. Extract generated alarms
        all_alarms = self._engine.get_all_alarms()

        # 3. Post-hoc evaluation strictly decoupled from detection decisions
        report = evaluate_detections(
            ground_truth=ground_truth,
            alarms=all_alarms,
            grace_period_seconds=grace_period_seconds,
        )

        return batch_result, report

    def replay_and_evaluate_pipeline(
        self,
        snapshots: Sequence[KPISnapshot],
        ground_truth: Sequence[GroundTruthRecord],
        topology: Topology,
        transport: Optional[TransportNetwork] = None,
        node_types: Optional[Mapping[str, Optional[NodeType]]] = None,
        grace_period_seconds: float = 60.0,
        correlation_engine: Optional[AlarmCorrelationEngine] = None,
        rca_engine: Optional[RootCauseAnalysisEngine] = None,
    ) -> tuple[
        DetectionBatchResult,
        EvaluationReport,
        CorrelationResult,
        list[RCAResult],
        RCAEvaluationReport,
    ]:
        """Full end-to-end replay through detection, correlation, and RCA with ground-truth evaluation.

        Guarantees:
        - Feeds ONLY telemetry snapshots to detection engine.
        - Correlates resulting alarms using topological hierarchy and symptom compatibility.
        - Evaluates RCA hypotheses against explainable diagnostic rules.
        - Evaluates both detection metrics (precision, recall, F1, MTTD) and RCA metrics (Top-1, Top-k, target correctness).
        - Ground truth remains strictly isolated for post-hoc validation only.
        """
        # 1. Detection
        batch_result = self._engine.process_batch(snapshots, node_types=node_types)
        all_alarms = self._engine.get_all_alarms()

        # 2. Post-hoc detection evaluation
        det_report = evaluate_detections(
            ground_truth=ground_truth,
            alarms=all_alarms,
            grace_period_seconds=grace_period_seconds,
        )

        # 3. Correlation
        corr = correlation_engine or AlarmCorrelationEngine(topology=topology, transport=transport)
        corr_result = corr.correlate(all_alarms, topology=topology, transport=transport)

        # 4. RCA
        rca = rca_engine or RootCauseAnalysisEngine(topology=topology, transport=transport)
        latest_ts = max((s.timestamp for s in snapshots), default=None)
        rca_results = rca.analyze_results(
            correlation_result=corr_result,
            topology=topology,
            transport=transport,
            telemetry_snapshots=snapshots,
            analysis_timestamp=latest_ts,
        )

        # 5. Post-hoc RCA evaluation
        rca_report = evaluate_rca(
            ground_truth=ground_truth,
            rca_results=rca_results,
            correlation_result=corr_result,
            grace_period_seconds=grace_period_seconds,
            transport=transport,
        )

        return batch_result, det_report, corr_result, rca_results, rca_report

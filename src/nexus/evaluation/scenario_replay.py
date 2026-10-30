"""Scenario replay and post-hoc evaluation coordinator."""

from typing import Mapping, Optional, Sequence

from nexus.detection.engine import AnomalyDetectionEngine, DetectionBatchResult
from nexus.evaluation.evaluator import evaluate_detections
from nexus.evaluation.models import EvaluationReport
from nexus.fault.models import GroundTruthRecord
from nexus.telemetry.models import KPISnapshot
from nexus.topology.enums import NodeType


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

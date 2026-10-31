"""NEXUS Evaluation Subsystem package."""

from nexus.evaluation.evaluator import evaluate_detections, evaluate_rca
from nexus.evaluation.models import (
    EvaluationReport,
    FaultDetectionMatch,
    RCAEvaluationReport,
    RCAGroundTruthMatch,
)
from nexus.evaluation.scenario_replay import ScenarioReplayEvaluator

__all__ = [
    "EvaluationReport",
    "FaultDetectionMatch",
    "RCAEvaluationReport",
    "RCAGroundTruthMatch",
    "ScenarioReplayEvaluator",
    "evaluate_detections",
    "evaluate_rca",
]

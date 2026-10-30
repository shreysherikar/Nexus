"""NEXUS Evaluation Subsystem package."""

from nexus.evaluation.evaluator import evaluate_detections
from nexus.evaluation.models import EvaluationReport, FaultDetectionMatch
from nexus.evaluation.scenario_replay import ScenarioReplayEvaluator

__all__ = [
    "EvaluationReport",
    "FaultDetectionMatch",
    "ScenarioReplayEvaluator",
    "evaluate_detections",
]

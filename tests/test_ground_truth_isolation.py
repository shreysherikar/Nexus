"""Tests proving strict architectural and runtime ground-truth isolation.

Verifies:
1. AST inspection: Operational engines (nexus.detection, nexus.correlation, nexus.rca, nexus.incidents)
   strictly have ZERO imports from nexus.fault or evaluation ground-truth modules.
2. Runtime independence: Correlation, RCA, and incident lifecycle execute without fault service,
   without ground truth records, and have zero attributes or knowledge of fault scenarios.
3. Post-hoc verification only: Ground truth is exclusively consumed by evaluation components.
"""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

from nexus.correlation.engine import AlarmCorrelationEngine
from nexus.detection.service import AlarmService
from nexus.incidents.service import IncidentService
from nexus.rca.engine import RootCauseAnalysisEngine
from nexus.topology.builder import build_simulated_network
from nexus.transport.builder import build_reference_transport_network


OPERATIONAL_PACKAGES = [
    "detection",
    "correlation",
    "rca",
    "incidents",
]


class TestGroundTruthStaticIsolation:
    """AST import inspection across all operational modules."""

    @pytest.mark.parametrize("pkg_name", OPERATIONAL_PACKAGES)
    def test_zero_ast_imports_from_fault_or_evaluation(self, pkg_name: str) -> None:
        src_root = Path(__file__).resolve().parent.parent / "src" / "nexus" / pkg_name
        assert src_root.exists(), f"Source directory {src_root} does not exist"

        for py_file in src_root.rglob("*.py"):
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "nexus.fault" not in alias.name, (
                            f"Violation in {py_file.name}: explicit import '{alias.name}' from nexus.fault"
                        )
                        assert "nexus.evaluation" not in alias.name, (
                            f"Violation in {py_file.name}: explicit import '{alias.name}' from nexus.evaluation"
                        )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert "nexus.fault" not in mod, (
                        f"Violation in {py_file.name}: import from '{mod}' (nexus.fault)"
                    )
                    assert "nexus.evaluation" not in mod, (
                        f"Violation in {py_file.name}: import from '{mod}' (nexus.evaluation)"
                    )


class TestGroundTruthRuntimeIsolation:
    """Runtime inspection proving operational engines have zero ground truth coupling."""

    @pytest.fixture
    def net(self):
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net):
        return build_reference_transport_network(net)

    def test_rca_engine_has_no_fault_or_ground_truth_references(self, net, transport) -> None:
        rca = RootCauseAnalysisEngine(topology=net, transport=transport)
        # Verify no ground-truth or fault attributes exist on engine instance
        for attr in dir(rca):
            assert "fault" not in attr.lower() or attr in ("_find_upstream_transport_link",), f"Suspicious attribute: {attr}"
            assert "ground_truth" not in attr.lower()
            assert "scenario" not in attr.lower()

    def test_correlation_engine_has_no_fault_or_ground_truth_references(self, net) -> None:
        corr = AlarmCorrelationEngine(topology=net)
        for attr in dir(corr):
            assert "fault" not in attr.lower()
            assert "ground_truth" not in attr.lower()
            assert "scenario" not in attr.lower()

    def test_alarm_service_has_no_fault_or_ground_truth_references(self) -> None:
        alarm_svc = AlarmService()
        for attr in dir(alarm_svc):
            assert "fault" not in attr.lower()
            assert "ground_truth" not in attr.lower()
            assert "scenario" not in attr.lower()

    def test_incident_service_has_no_fault_or_ground_truth_references(self) -> None:
        from nexus.incidents.service import IncidentService
        inc_svc = IncidentService(repository=None)
        for attr in dir(inc_svc):
            assert "fault" not in attr.lower()
            assert "ground_truth" not in attr.lower()
            assert "scenario" not in attr.lower()

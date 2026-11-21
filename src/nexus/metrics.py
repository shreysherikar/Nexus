"""Prometheus metrics engine for NEXUS Network Intelligence & Incident Management Platform.

This module provides Prometheus instrumentation for the NEXUS platform:
- Low-cardinality HTTP request counters and latency histograms using normalized route templates.
- Application readiness and component-level health gauges.
- Authoritative telemetry domain metrics aggregated by network tier.
- Active and lifecycle alarm metrics by severity and status.
- Incident lifecycle and SLA compliance performance metrics.
- Fault injection scenario status and affected node counts.

Architectural Constraints:
- Strict bounded cardinality: never emit dynamic IDs (node_id, alarm_id, incident_id), timestamps,
  or operator notes in Prometheus labels.
- Ground truth isolation: ground truth is strictly for evaluation; never emit ground-truth data in metrics.
- Exclude /metrics from recursive HTTP request tracking to prevent scrape distortion.
- Scrapes update Gauges reflecting point-in-time state without duplicate Counter incrementation.
- Thread-safe and isolated CollectorRegistry support for unit and integration testing.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Optional, Sequence

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger("nexus.metrics")

# Standard bounded label sets
VALID_NODE_TIERS = ("CORE", "AGGREGATION", "SITE", "CELL")
VALID_ALARM_SEVERITIES = ("CRITICAL", "MAJOR", "WARNING")
VALID_ALARM_STATUSES = ("ACTIVE", "CLEARED")
VALID_INCIDENT_SEVERITIES = ("CRITICAL", "MAJOR", "WARNING", "MINOR")
VALID_INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "RESOLVED")
VALID_SLA_TYPES = ("acknowledgement", "resolution")
VALID_FAULT_SCENARIOS = (
    "cell_outage",
    "backhaul_failure",
    "radio_interference",
    "cell_congestion",
    "site_power_failure",
)
VALID_COMPONENTS = (
    "topology",
    "broadcaster",
    "telemetry_store",
    "alarm_service",
    "fault_service",
    "database",
)

# Standard latency buckets (in seconds) suitable for sub-millisecond to multi-second operations
DEFAULT_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def normalize_endpoint(request: Request) -> str:
    """Extract a normalized route template from the request to guarantee bounded cardinality.

    Args:
        request: The active Starlette/FastAPI HTTP request.

    Returns:
        The registered route path template (e.g. '/api/v1/incidents/{incident_id}')
        or 'unmatched' if the route did not match any handler.
    """
    route = request.scope.get("route")
    if route and hasattr(route, "path") and isinstance(route.path, str):
        return route.path
    return "unmatched"


class NexusMetricsManager:
    """Thread-safe Prometheus metrics registry and domain gauge updater for NEXUS."""

    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry(auto_describe=True)
        self._lock = threading.RLock()
        self._incident_cache: Optional[Any] = None
        self._incident_cache_time: float = 0.0

        # --- 1. HTTP Request Metrics (Process Lifetime Counters & Histograms) ---
        self.http_requests_total = Counter(
            "nexus_http_requests_total",
            "Total HTTP requests processed by endpoint template, method, and HTTP status code.",
            ["method", "endpoint", "status"],
            registry=self.registry,
        )
        self.http_request_duration_seconds = Histogram(
            "nexus_http_request_duration_seconds",
            "HTTP request processing latency in seconds by endpoint template and method.",
            ["method", "endpoint"],
            buckets=DEFAULT_LATENCY_BUCKETS,
            registry=self.registry,
        )

        # --- 2. Application Info & Readiness Gauges ---
        self.app_info = Gauge(
            "nexus_app_info",
            "Platform build version and metadata information.",
            ["version", "platform"],
            registry=self.registry,
        )
        self.app_info.labels(version="1.0.0", platform="NEXUS").set(1.0)

        self.ready_status = Gauge(
            "nexus_ready_status",
            "Overall application operational readiness (1=ready, 0=not ready).",
            registry=self.registry,
        )
        self.component_ready = Gauge(
            "nexus_component_ready",
            "Readiness state of individual application subsystems (1=ready, 0=not ready).",
            ["component"],
            registry=self.registry,
        )
        for comp in VALID_COMPONENTS:
            self.component_ready.labels(component=comp).set(0.0)

        # --- 3. Telemetry Domain Metrics (Aggregated by Node Tier) ---
        self.telemetry_snapshots_total = Gauge(
            "nexus_telemetry_snapshots_total",
            "Total number of authentic telemetry snapshots currently retained in the memory store.",
            registry=self.registry,
        )
        self.telemetry_last_timestamp_seconds = Gauge(
            "nexus_telemetry_last_timestamp_seconds",
            "UTC epoch timestamp of the most recent telemetry observation snapshot.",
            registry=self.registry,
        )
        self.telemetry_throughput_mbps_avg = Gauge(
            "nexus_telemetry_throughput_mbps_avg",
            "Average network throughput in Megabits per second aggregated by topological node tier.",
            ["node_tier"],
            registry=self.registry,
        )
        self.telemetry_latency_ms_avg = Gauge(
            "nexus_telemetry_latency_ms_avg",
            "Average network latency in milliseconds aggregated by topological node tier.",
            ["node_tier"],
            registry=self.registry,
        )
        self.telemetry_drop_rate_pct_avg = Gauge(
            "nexus_telemetry_drop_rate_pct_avg",
            "Average packet / connection drop rate percentage aggregated by topological node tier.",
            ["node_tier"],
            registry=self.registry,
        )
        self.telemetry_availability_pct_avg = Gauge(
            "nexus_telemetry_availability_pct_avg",
            "Average operational availability percentage aggregated by topological node tier.",
            ["node_tier"],
            registry=self.registry,
        )
        self.telemetry_radio_sinr_db_avg = Gauge(
            "nexus_telemetry_radio_sinr_db_avg",
            "Average radio Signal-to-Interference-plus-Noise ratio in dB across active CELL nodes.",
            registry=self.registry,
        )
        self.telemetry_radio_prb_utilization_pct_avg = Gauge(
            "nexus_telemetry_radio_prb_utilization_pct_avg",
            "Average Physical Resource Block utilization percentage across active CELL nodes.",
            registry=self.registry,
        )
        # Initialize tier gauges with 0.0
        for tier in VALID_NODE_TIERS:
            self.telemetry_throughput_mbps_avg.labels(node_tier=tier).set(0.0)
            self.telemetry_latency_ms_avg.labels(node_tier=tier).set(0.0)
            self.telemetry_drop_rate_pct_avg.labels(node_tier=tier).set(0.0)
            self.telemetry_availability_pct_avg.labels(node_tier=tier).set(0.0)
        self.telemetry_radio_sinr_db_avg.set(0.0)
        self.telemetry_radio_prb_utilization_pct_avg.set(0.0)
        self.telemetry_snapshots_total.set(0.0)
        self.telemetry_last_timestamp_seconds.set(0.0)

        # --- 4. Alarm Metrics ---
        self.alarms_active = Gauge(
            "nexus_alarms_active",
            "Number of currently active network alarms by severity classification.",
            ["severity"],
            registry=self.registry,
        )
        self.alarms_total = Gauge(
            "nexus_alarms_total",
            "Total tracked network alarms by severity classification and lifecycle status.",
            ["severity", "status"],
            registry=self.registry,
        )
        for sev in VALID_ALARM_SEVERITIES:
            self.alarms_active.labels(severity=sev).set(0.0)
            for st in VALID_ALARM_STATUSES:
                self.alarms_total.labels(severity=sev, status=st).set(0.0)

        # --- 5. Incident & SLA Performance Metrics ---
        self.incidents_total = Gauge(
            "nexus_incidents_total",
            "Total operational incidents recorded across the system.",
            registry=self.registry,
        )
        self.incidents_active = Gauge(
            "nexus_incidents_active",
            "Number of active, unresolved operational incidents by severity classification.",
            ["severity"],
            registry=self.registry,
        )
        self.incidents_by_status = Gauge(
            "nexus_incidents_by_status",
            "Total operational incidents categorized by lifecycle status.",
            ["status"],
            registry=self.registry,
        )
        self.incidents_by_severity = Gauge(
            "nexus_incidents_by_severity",
            "Total operational incidents categorized by severity classification.",
            ["severity"],
            registry=self.registry,
        )
        self.incidents_sla_breaches_total = Gauge(
            "nexus_incidents_sla_breaches_total",
            "Total incident SLA breaches recorded by SLA obligation type.",
            ["sla_type"],
            registry=self.registry,
        )
        self.incidents_mtta_seconds = Gauge(
            "nexus_incidents_mtta_seconds",
            "Mean Time To Acknowledge across acknowledged operational incidents in seconds.",
            registry=self.registry,
        )
        self.incidents_mttr_seconds = Gauge(
            "nexus_incidents_mttr_seconds",
            "Mean Time To Resolve across resolved operational incidents in seconds.",
            registry=self.registry,
        )
        self.incidents_mttd_seconds = Gauge(
            "nexus_incidents_mttd_seconds",
            "Mean Time To Detect from injected fault onset to first detection in seconds.",
            registry=self.registry,
        )
        self.incidents_sla_compliance_pct = Gauge(
            "nexus_incidents_sla_compliance_pct",
            "Authoritative SLA compliance percentage across evaluated operational incidents.",
            registry=self.registry,
        )
        for sev in VALID_INCIDENT_SEVERITIES:
            self.incidents_active.labels(severity=sev).set(0.0)
            self.incidents_by_severity.labels(severity=sev).set(0.0)
        for st in VALID_INCIDENT_STATUSES:
            self.incidents_by_status.labels(status=st).set(0.0)
        for sla in VALID_SLA_TYPES:
            self.incidents_sla_breaches_total.labels(sla_type=sla).set(0.0)
        self.incidents_total.set(0.0)
        self.incidents_mtta_seconds.set(0.0)
        self.incidents_mttr_seconds.set(0.0)
        self.incidents_mttd_seconds.set(0.0)
        self.incidents_sla_compliance_pct.set(100.0)

        # --- 6. Fault Injection Metrics ---
        self.fault_scenario_active = Gauge(
            "nexus_fault_scenario_active",
            "Active state of reference fault scenarios (1=active, 0=inactive).",
            ["scenario_key"],
            registry=self.registry,
        )
        self.fault_affected_nodes_count = Gauge(
            "nexus_fault_affected_nodes_count",
            "Number of topological network nodes currently impacted by active fault injection.",
            registry=self.registry,
        )
        for key in VALID_FAULT_SCENARIOS:
            self.fault_scenario_active.labels(scenario_key=key).set(0.0)
        self.fault_affected_nodes_count.set(0.0)

    def record_http_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record an authentic HTTP request observation.

        Args:
            method: Standard HTTP method (e.g. 'GET', 'POST').
            endpoint: Normalized route template (e.g. '/api/v1/topology').
            status_code: HTTP response status code.
            duration_seconds: Request processing duration in seconds.
        """
        method_str = method.upper().strip()
        status_str = str(status_code)
        self.http_requests_total.labels(
            method=method_str, endpoint=endpoint, status=status_str
        ).inc()
        self.http_request_duration_seconds.labels(
            method=method_str, endpoint=endpoint
        ).observe(max(0.0, duration_seconds))

    def update_domain_metrics(self) -> None:
        """Sample authoritative application subsystems and refresh all Prometheus Gauges."""
        with self._lock:
            self._update_readiness_metrics()
            self._update_telemetry_metrics()
            self._update_alarm_metrics()
            self._update_incident_metrics()
            self._update_fault_metrics()

    def _update_readiness_metrics(self) -> None:
        """Verify readiness across all 6 core platform subsystems."""
        is_all_ready = True

        # 1. Topology
        try:
            from nexus.topology.api import get_topology_registry

            topo = get_topology_registry()
            node_count = len(topo) if hasattr(topo, "__len__") else len(topo.all_nodes())
            ready = node_count > 0
            self.component_ready.labels(component="topology").set(1.0 if ready else 0.0)
            if not ready:
                is_all_ready = False
        except Exception:
            self.component_ready.labels(component="topology").set(0.0)
            is_all_ready = False

        # 2. Broadcaster
        try:
            from nexus.events.broadcaster import get_broadcaster

            broadcaster = get_broadcaster()
            ready = broadcaster is not None
            self.component_ready.labels(component="broadcaster").set(1.0 if ready else 0.0)
            if not ready:
                is_all_ready = False
        except Exception:
            self.component_ready.labels(component="broadcaster").set(0.0)
            is_all_ready = False

        # 3. Telemetry Store
        try:
            from nexus.telemetry.store import get_telemetry_store

            store = get_telemetry_store()
            ready = store is not None
            self.component_ready.labels(component="telemetry_store").set(1.0 if ready else 0.0)
            if not ready:
                is_all_ready = False
        except Exception:
            self.component_ready.labels(component="telemetry_store").set(0.0)
            is_all_ready = False

        # 4. Alarm Service
        try:
            from nexus.detection.service import get_alarm_service

            alarm_svc = get_alarm_service()
            ready = alarm_svc is not None
            self.component_ready.labels(component="alarm_service").set(1.0 if ready else 0.0)
            if not ready:
                is_all_ready = False
        except Exception:
            self.component_ready.labels(component="alarm_service").set(0.0)
            is_all_ready = False

        # 5. Fault Service
        try:
            from nexus.fault.service import get_fault_service

            fault_svc = get_fault_service()
            ready = fault_svc is not None
            self.component_ready.labels(component="fault_service").set(1.0 if ready else 0.0)
            if not ready:
                is_all_ready = False
        except Exception:
            self.component_ready.labels(component="fault_service").set(0.0)
            is_all_ready = False

        # 6. Database / Incident Service
        try:
            from nexus.incidents.api import get_incident_service

            svc = get_incident_service()
            ready = svc is not None
            self.component_ready.labels(component="database").set(1.0 if ready else 0.0)
            if not ready:
                is_all_ready = False
        except Exception:
            self.component_ready.labels(component="database").set(0.0)
            is_all_ready = False

        self.ready_status.set(1.0 if is_all_ready else 0.0)

    def _update_telemetry_metrics(self) -> None:
        """Sample TelemetryStore and compute tier-aggregated KPI averages."""
        try:
            from nexus.telemetry.store import get_telemetry_store
            from nexus.topology.api import get_topology_registry

            store = get_telemetry_store()
            topo = get_topology_registry()

            count = store.count
            self.telemetry_snapshots_total.set(float(count))

            if count == 0:
                self.telemetry_last_timestamp_seconds.set(0.0)
                for tier in VALID_NODE_TIERS:
                    self.telemetry_throughput_mbps_avg.labels(node_tier=tier).set(0.0)
                    self.telemetry_latency_ms_avg.labels(node_tier=tier).set(0.0)
                    self.telemetry_drop_rate_pct_avg.labels(node_tier=tier).set(0.0)
                    self.telemetry_availability_pct_avg.labels(node_tier=tier).set(0.0)
                self.telemetry_radio_sinr_db_avg.set(0.0)
                self.telemetry_radio_prb_utilization_pct_avg.set(0.0)
                return

            # Extract the latest snapshot for each distinct node from the buffer
            with store._lock:
                snapshots_copy = list(store._buffer)

            latest_by_node: dict[str, Any] = {}
            for s in snapshots_copy:
                latest_by_node[s.node_id] = s

            # Calculate latest observation timestamp across nodes
            latest_ts = max(s.timestamp.timestamp() for s in latest_by_node.values())
            self.telemetry_last_timestamp_seconds.set(latest_ts)

            # Helper to map node_id to tier
            def get_tier(nid: str) -> str:
                if topo and topo.has_node(nid):
                    return topo.get_node(nid).node_type.value
                if nid.startswith("CORE"):
                    return "CORE"
                if nid.startswith("AGG"):
                    return "AGGREGATION"
                if nid.startswith("SITE"):
                    return "SITE"
                if nid.startswith("CELL"):
                    return "CELL"
                return "CELL"

            # Aggregate by tier
            tier_data: dict[str, dict[str, list[float]]] = {
                t: {"throughput": [], "latency": [], "drop_rate": [], "availability": []}
                for t in VALID_NODE_TIERS
            }
            cell_sinr: list[float] = []
            cell_prb: list[float] = []

            for s in latest_by_node.values():
                tier = get_tier(s.node_id)
                if tier not in tier_data:
                    continue
                tier_data[tier]["throughput"].append(s.performance.throughput_mbps)
                tier_data[tier]["latency"].append(s.performance.latency_ms)
                tier_data[tier]["drop_rate"].append(s.reliability.connection_drop_rate_pct)
                tier_data[tier]["availability"].append(s.reliability.availability_pct)

                if tier == "CELL" and s.radio is not None:
                    cell_sinr.append(s.radio.sinr_db)
                    cell_prb.append(s.radio.prb_utilization_pct)

            for tier, metrics in tier_data.items():
                tp_avg = (
                    sum(metrics["throughput"]) / len(metrics["throughput"])
                    if metrics["throughput"]
                    else 0.0
                )
                lat_avg = (
                    sum(metrics["latency"]) / len(metrics["latency"])
                    if metrics["latency"]
                    else 0.0
                )
                drop_avg = (
                    sum(metrics["drop_rate"]) / len(metrics["drop_rate"])
                    if metrics["drop_rate"]
                    else 0.0
                )
                avail_avg = (
                    sum(metrics["availability"]) / len(metrics["availability"])
                    if metrics["availability"]
                    else 0.0
                )

                self.telemetry_throughput_mbps_avg.labels(node_tier=tier).set(tp_avg)
                self.telemetry_latency_ms_avg.labels(node_tier=tier).set(lat_avg)
                self.telemetry_drop_rate_pct_avg.labels(node_tier=tier).set(drop_avg)
                self.telemetry_availability_pct_avg.labels(node_tier=tier).set(avail_avg)

            sinr_avg = sum(cell_sinr) / len(cell_sinr) if cell_sinr else 0.0
            prb_avg = sum(cell_prb) / len(cell_prb) if cell_prb else 0.0
            self.telemetry_radio_sinr_db_avg.set(sinr_avg)
            self.telemetry_radio_prb_utilization_pct_avg.set(prb_avg)

        except Exception as exc:
            logger.warning("Error updating telemetry metrics: %s", exc)

    def _update_alarm_metrics(self) -> None:
        """Sample AlarmService and update active and total alarm gauges."""
        try:
            from nexus.detection.service import get_alarm_service

            alarm_svc = get_alarm_service()
            active_counts: dict[str, int] = {sev: 0 for sev in VALID_ALARM_SEVERITIES}
            total_counts: dict[tuple[str, str], int] = {
                (sev, st): 0 for sev in VALID_ALARM_SEVERITIES for st in VALID_ALARM_STATUSES
            }

            all_alarms = alarm_svc.manager.get_all_alarms()
            for a in all_alarms:
                sev = a.severity.value
                st = a.status.value
                if (sev, st) in total_counts:
                    total_counts[(sev, st)] += 1
                if st == "ACTIVE" and sev in active_counts:
                    active_counts[sev] += 1

            for sev, cnt in active_counts.items():
                self.alarms_active.labels(severity=sev).set(float(cnt))

            for (sev, st), cnt in total_counts.items():
                self.alarms_total.labels(severity=sev, status=st).set(float(cnt))

        except Exception as exc:
            logger.warning("Error updating alarm metrics: %s", exc)

    def _update_incident_metrics(self) -> None:
        """Sample IncidentService and update lifecycle, status, severity, and SLA gauges."""
        try:
            from nexus.incidents.api import get_incident_service
            from nexus.incidents.enums import IncidentSeverity, IncidentStatus

            svc = get_incident_service()
            if svc is None:
                return

            now = time.monotonic()
            # Reuse cached report if polled within 2 seconds to avoid excessive DB reads
            if self._incident_cache is not None and (now - self._incident_cache_time) < 2.0:
                report = self._incident_cache
            else:
                report = svc.get_metrics()
                self._incident_cache = report
                self._incident_cache_time = now

            self.incidents_total.set(float(report.total_incidents))

            # Incident counts by status
            for st in VALID_INCIDENT_STATUSES:
                cnt = report.incidents_by_status.get(st, 0)
                self.incidents_by_status.labels(status=st).set(float(cnt))

            # Incident counts by severity
            for sev in VALID_INCIDENT_SEVERITIES:
                cnt = report.incidents_by_severity.get(sev, 0)
                self.incidents_by_severity.labels(severity=sev).set(float(cnt))

            # Active incidents by severity (unresolved: OPEN or ACKNOWLEDGED)
            active_by_sev = {sev: 0 for sev in VALID_INCIDENT_SEVERITIES}
            for inc in svc._repo.iter_all_incidents():
                if inc.status in (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED):
                    sev_val = inc.severity.value
                    if sev_val in active_by_sev:
                        active_by_sev[sev_val] += 1

            for sev, cnt in active_by_sev.items():
                self.incidents_active.labels(severity=sev).set(float(cnt))

            # SLA breaches
            self.incidents_sla_breaches_total.labels(sla_type="acknowledgement").set(
                float(report.ack_sla_breached_count)
            )
            self.incidents_sla_breaches_total.labels(sla_type="resolution").set(
                float(report.resolve_sla_breached_count)
            )

            # SLA performance numbers
            self.incidents_mtta_seconds.set(
                float(report.mtta_seconds) if report.mtta_seconds is not None else 0.0
            )
            self.incidents_mttr_seconds.set(
                float(report.mttr_seconds) if report.mttr_seconds is not None else 0.0
            )
            self.incidents_mttd_seconds.set(
                float(report.mttd_seconds) if report.mttd_seconds is not None else 0.0
            )
            self.incidents_sla_compliance_pct.set(
                float(report.sla_compliance_pct)
                if report.sla_compliance_pct is not None
                else 100.0
            )

        except Exception as exc:
            logger.debug("Database / incident metrics unavailable: %s", exc)

    def _update_fault_metrics(self) -> None:
        """Sample FaultService and update scenario status and affected node count."""
        try:
            from nexus.fault.service import get_fault_service

            fault_svc = get_fault_service()
            active_sc = fault_svc.get_active_scenario()

            for key in VALID_FAULT_SCENARIOS:
                is_active = active_sc.active and active_sc.scenario_key == key
                self.fault_scenario_active.labels(scenario_key=key).set(1.0 if is_active else 0.0)

            if active_sc.active and active_sc.faults:
                affected_set: set[str] = set()
                for f in active_sc.faults:
                    affected_set.update(f.affected_nodes)
                self.fault_affected_nodes_count.set(float(len(affected_set)))
            else:
                self.fault_affected_nodes_count.set(0.0)

        except Exception as exc:
            logger.warning("Error updating fault metrics: %s", exc)

    def generate_metrics_response(self) -> Response:
        """Sample application state and generate Prometheus exposition text response."""
        self.update_domain_metrics()
        output = generate_latest(self.registry)
        return Response(
            content=output,
            media_type=CONTENT_TYPE_LATEST,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


_default_metrics_manager: Optional[NexusMetricsManager] = None
_metrics_lock = threading.Lock()


def get_metrics_manager() -> NexusMetricsManager:
    """Retrieve or initialize the global NexusMetricsManager singleton."""
    global _default_metrics_manager
    with _metrics_lock:
        if _default_metrics_manager is None:
            _default_metrics_manager = NexusMetricsManager()
        return _default_metrics_manager


def set_metrics_manager(manager: NexusMetricsManager) -> None:
    """Override the global NexusMetricsManager singleton (useful for isolated tests)."""
    global _default_metrics_manager
    with _metrics_lock:
        _default_metrics_manager = manager


def reset_metrics_manager() -> NexusMetricsManager:
    """Recreate the global NexusMetricsManager singleton with a fresh CollectorRegistry."""
    global _default_metrics_manager
    with _metrics_lock:
        _default_metrics_manager = NexusMetricsManager()
        return _default_metrics_manager

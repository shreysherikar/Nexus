"""Pydantic schemas for Telemetry REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class RadioMetricsResponse(BaseModel):
    rsrp_dbm: float = Field(..., description="Reference Signal Received Power in dBm")
    sinr_db: float = Field(..., description="Signal-to-Interference-plus-Noise Ratio in dB")
    prb_utilization_pct: float = Field(..., description="Physical Resource Block utilization [0-100%]")


class PerformanceMetricsResponse(BaseModel):
    throughput_mbps: float = Field(..., description="Throughput in Mbps")
    latency_ms: float = Field(..., description="Latency in milliseconds")


class ReliabilityMetricsResponse(BaseModel):
    connection_drop_rate_pct: float = Field(..., description="Connection drop rate percentage [0-100%]")
    availability_pct: float = Field(..., description="Service availability percentage [0-100%]")
    handover_success_rate_pct: Optional[float] = Field(None, description="Handover success rate percentage [0-100%] or null")


class KPISnapshotResponse(BaseModel):
    node_id: str = Field(..., description="Identifier of reporting node")
    timestamp: datetime = Field(..., description="Observation UTC timestamp")
    performance: PerformanceMetricsResponse = Field(..., description="Performance metrics")
    reliability: ReliabilityMetricsResponse = Field(..., description="Reliability metrics")
    radio: Optional[RadioMetricsResponse] = Field(None, description="Radio metrics or null for non-radio nodes")


class TelemetryListResponse(BaseModel):
    items: list[KPISnapshotResponse] = Field(..., description="List of telemetry snapshots")
    total: int = Field(..., description="Total matching snapshots count")
    limit: int = Field(..., description="Pagination limit")
    offset: int = Field(..., description="Pagination offset")


class TelemetryGenerateStepResponse(BaseModel):
    generated_count: int = Field(..., description="Count of genuine snapshots generated in this simulation step")
    timestamp: datetime = Field(..., description="UTC timestamp of the generated step")
    message: str = Field(..., description="Simulation generation status message")

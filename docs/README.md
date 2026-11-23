# NEXUS Technical Documentation Index

Welcome to the technical documentation for the **NEXUS Network Intelligence & Incident Management Platform**.

This directory contains comprehensive specifications, architectural designs, operational guides, and API references for the NEXUS platform.

---

## Architecture Specifications

Detailed domain specifications for core subsystems located in [`docs/architecture/`](architecture/):

- **[System Overview](architecture/system-overview.md)**: Architectural purpose, hierarchical 27-node topology model, 26 transport links, and end-to-end data processing pipeline.
- **[Telemetry & KPI Model](architecture/telemetry-and-kpi-model.md)**: Composite snapshot architecture, KPI definitions (latency, throughput, availability, SINR, PRB), operational profiles, and synthetic generation.
- **[Anomaly Detection](architecture/anomaly-detection.md)**: Static threshold rules with hysteresis anti-flapping, statistical detectors (Rolling Median MAD, EWMA), alarm lifecycle state machine, and ground-truth evaluation.
- **[Alarm Correlation & RCA](architecture/alarm-correlation-and-rca.md)**: Topological Lowest Common Ancestor (LCA) grouping, symptom compatibility filtering, multi-hypothesis scoring, and diagnostic evidence attribution.
- **[Incident Management & SLA Tracking](architecture/incident-management.md)**: Persistent incident domain model, operational severity policy (P1-P4), SLA deadline tracking (MTTA, MTTR), and append-only audit timeline.
- **[Fault Simulation Engine](architecture/fault-simulation.md)**: Controlled scenario engine, the six reference telecom fault scenarios, blast radius propagation, and recovery verification.
- **[Frontend Architecture](architecture/frontend-architecture.md)**: React 18 / TypeScript SPA, Dark NOC design system, state synchronization, REST client, and real-time WebSocket infrastructure.

---

## Architectural Decision Records (ADRs)

Key architectural decisions recorded in [`docs/decisions/`](decisions/):

- **[ADR-001: Modular Monolithic Architecture](decisions/ADR-001-project-architecture.md)**: Modular service-oriented monolith design, domain boundaries, technology stack, and persistence strategy.

---

## Operational and Integration Guides

System-level guides located in [`docs/`](.):

- **[API & WebSocket Specification](api-and-websocket.md)**: Complete REST API reference across all `/api/v1` routes and `/ws/live` real-time WebSocket protocol contracts.
- **[Database Schema & Migrations](database-schema-migrations.md)**: SQLAlchemy 2.x relational models, table definitions, foreign keys, and Alembic database migration procedures.
- **[Observability & Monitoring Deployment](observability-deployment.md)**: Prometheus time-series metrics catalog, scrape configuration, PromQL operational queries, and Docker Compose deployment hardening.
- **[Operations Runbook](operations-runbook.md)**: Step-by-step verification procedures, local startup, Docker Compose deployment, fault scenario triggers, and incident triage workflows.
- **[Testing & Verification Strategy](testing-verification.md)**: Automated testing strategy, backend pytest suite, frontend Vitest/TypeScript checks, end-to-end acceptance testing, and CI pipelines.

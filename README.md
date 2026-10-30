# NEXUS — Network Intelligence & Incident Management Platform

[![CI](https://github.com/shreysherikar/Nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/shreysherikar/Nexus/actions/workflows/ci.yml)

## Project Overview

NEXUS is an independent, modular software platform engineered to provide real-time network intelligence, telemetry analysis, topology visualization, and automated incident triage for modern telecommunications and distributed IP infrastructure.

Designed as an extensible, vendor-agnostic system, NEXUS unifies telemetry streams, models hierarchical network relationships, correlates cross-domain anomalies, and streamlines incident management workflows for Network Operations Centers (NOCs) and infrastructure engineering teams.

> **Network Data Simulation Notice**  
> All network telemetry, topology nodes, alarm events, performance counters, and traffic flows in this platform are initially generated via a deterministic, synthetic simulation engine. NEXUS operates independently without requiring live carrier connections, external production networks, or physical laboratory hardware.

---

## Problem Statement

Modern telecommunications and large-scale distributed networks face substantial operational challenges:

1. **Alarm Fatigue and High Noise Ratios**: NOC engineers are frequently overwhelmed by thousands of raw alarms generated during transient fluctuations or cascading faults.
2. **Fragmented Telemetry**: Metrics, syslog events, and alarm traps are siloed across disconnected tools, preventing a unified operational view.
3. **Delayed Root-Cause Analysis (RCA)**: Without real-time topological context, identifying whether a service degradation originates at a core gateway, backhaul aggregation link, or individual radio cell requires laborious manual investigation.
4. **Manual Triage Overhead**: Static ticketing systems lack automated correlation, resulting in duplicate tickets, incorrect severity assignment, and delayed mean-time-to-repair (MTTR).

---

## Project Objectives

- **Hierarchical Telemetry Ingestion**: Ingest and normalize multi-tier time-series metrics and alarm events across core, aggregation, site, and cell layers.
- **Topology-Aware Correlation**: Map alarms and anomalies against an active topological graph to isolate root causes and suppress downstream symptoms.
- **Automated Incident Lifecycle**: Generate, enrich, and prioritize operational incidents with automated blast-radius calculations and status workflows.
- **Interactive Operational Visibility**: Deliver a responsive, intuitive web dashboard featuring dynamic topology graphs, KPI trends, and incident workbenches.
- **Developer-Friendly & Modular Foundation**: Provide a clean, testable architecture capable of running locally without costly cloud dependencies, ready for incremental extension.

---

## Planned High-Level Capabilities

- **Synthetic Network Simulation**: Configurable network generator capable of modeling healthy baseline operations as well as controlled fault scenarios (e.g., link flaps, fiber cuts, cell congestion, power failures).
- **Metric Processing & KPI Aggregation**: Ingestion pipeline computing rolling-window KPIs (latency, packet loss, throughput, radio link availability, error rates).
- **Topology Engine**: Graph-based representation of network elements, parent-child links, and operational states across Core, Aggregation, Site, and Cell tiers.
- **Correlation & Anomaly Engine**: Rule-based and statistical evaluation to detect anomalies and perform parent-child alarm suppression.
- **Incident Workbench**: Centralized management interface for active incidents, root-cause summaries, affected element listings, and triage actions.

---

## Planned Technology Stack

- **Backend Service Layer**: Python 3.11+ using FastAPI for asynchronous REST and WebSocket APIs, Pydantic for data validation, and modular domain engines.
- **Frontend Operations Console**: TypeScript, React, and Vite, complemented by modern UI styling and interactive graph visualization (such as React Flow / Cytoscape).
- **Data & State Management**: Lightweight local storage (SQLite for structured application metadata; DuckDB / local time-series tables for high-throughput simulated metric evaluation).
- **Environment & Tooling**: Git, standard package managers (`pip` / `uv` for Python, `pnpm` / `npm` for Node.js), and comprehensive automated testing (`pytest`).
- **Deployment & Portability**: Completely self-contained local development environment without mandatory cloud infrastructure, Kubernetes, or proprietary managed services.

---

## Repository Structure

```
nexus-network-intelligence/
├── .gitignore
├── README.md
└── docs/
    ├── architecture/
    │   └── initial-design.md
    └── decisions/
        └── ADR-001-project-architecture.md
```

---

## Getting Started & Roadmap

This repository is currently in its initial foundation stage. Development follows a modular, incremental roadmap:

1. **Phase 1: Workspace & Architectural Foundation** *(Current)*
2. **Phase 2: Topology Modeling & Synthetic Simulation Engine**
3. **Phase 3: Telemetry Ingestion & Anomaly Detection**
4. **Phase 4: Incident Correlation & Root-Cause Analysis**
5. **Phase 5: Interactive Operations Dashboard & UI**

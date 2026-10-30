# ADR-001: Initial Project Architecture and Modular Design

- **Status**: Accepted
- **Date**: 2026-10-30
- **Deciders**: NEXUS Core Engineering
- **Technical Domain**: System Architecture & Repository Structure

---

## Context

We are initiating the NEXUS platform (Network Intelligence & Incident Management Platform). The goal is to provide real-time telemetry processing, hierarchical topology modeling, anomaly detection, and automated incident triage for telecommunications and IP networks.

Key engineering constraints and project conditions:
1. The platform must be developed incrementally without upfront bloat or premature operational overhead.
2. Initial network telemetry and topology will be completely synthetic/simulated.
3. The platform must execute reliably on standard local developer environments without requiring paid cloud services, complex container orchestrators (such as Kubernetes), or heavy distributed streaming middleware.
4. The system will eventually evolve to support larger topologies, complex correlation heuristics, and modern web operational dashboards.

We must establish an architectural direction that balances developer velocity and simplicity with strict boundaries, high testability, and future extensibility.

---

## Decision

We adopt a **modular monolithic architecture** (Service-Oriented Monolith) organised into decoupled domain modules, paired with a modern asynchronous backend (Python / FastAPI) and an independent typed web frontend (TypeScript / React).

### 1. Decoupled Domain Boundaries

The backend system is partitioned into discrete, independent domain modules:

- **`topology`**: Encapsulates network nodes, hierarchical graph relations (Core -> Aggregation -> Site -> Cell), status representations, and graph traversal algorithms.
- **`simulation`**: Houses the synthetic network generator, fault-injection engine, and scenario controllers. Completely isolated so it can be enabled, disabled, or swapped for external telemetry feeds without altering downstream logic.
- **`telemetry`**: Ingests, normalizes, and aggregates time-series metrics (latency, packet loss, bandwidth, radio availability) and threshold alerts.
- **`correlation`**: Implements topological correlation, symptom suppression, and root-cause analysis (RCA) logic independently from data ingestion.
- **`incident`**: Manages incident synthesis, blast-radius calculation, lifecycle transitions, and operator audit records.
- **`api`**: Provides RESTful and WebSocket interfaces exposing domain capabilities to operators and external consumers.

### 2. Technology Stack Selection

- **Backend**: Python 3.11+ with FastAPI.
  - *Rationale*: Python offers an exceptional ecosystem for telemetry evaluation, graph algorithms, and data modeling. FastAPI provides asynchronous request handling, automatic OpenAPI documentation, and native Pydantic schema validation.
- **Persistence**: Embedded / lightweight local storage (SQLite for relational records; DuckDB or in-memory arrays for rolling telemetry).
  - *Rationale*: Minimizes external dependencies; zero configuration required to run tests or execute the application locally.
- **Frontend**: TypeScript + React + Vite.
  - *Rationale*: Type-safe UI development, rich ecosystem for topology visualization (React Flow / Cytoscape), and rapid local development cycles.

---

## Consequences

### Positive Consequences

- **High Velocity & Low Friction**: Developers can clone the repository and run tests or start services locally in seconds without spinning up Docker clusters, cloud credentials, or Kubernetes pods.
- **Clean Separation of Concerns**: Clear module boundaries enforce high cohesion and low coupling. Domain logic remains pure and decoupled from framework or transport details.
- **Testability**: In-memory domain modules and simulation components can be comprehensively tested with automated unit and integration tests using `pytest`.
- **Incremental Evolution**: If specific components (e.g., the correlation engine or high-throughput telemetry ingestion) require independent horizontal scaling in the future, modular boundaries make extraction into standalone microservices straightforward.

### Negative Consequences & Mitigations

- **Single-Node Resource Limits**: A monolithic runtime is bound to the resources of a single machine.
  - *Mitigation*: Our initial target scale is a 27-node simulated network, where single-machine throughput (thousands of events per second) is more than sufficient.
- **Risk of Domain Leaks**: In a shared codebase, developers might be tempted to bypass domain boundaries.
  - *Mitigation*: Strict boundary conventions, clear directory structure, and linting rules will enforce unidirectional dependencies.

---

## Alternatives Considered

1. **Distributed Microservices with Kafka & Kubernetes**:
   - *Pros*: Independent scalability, isolated deployables.
   - *Cons*: Immense operational complexity, distributed transaction hurdles, heavy local resource usage, and significant cognitive overhead early in development.
   - *Verdict*: Rejected as premature optimization.

2. **Single Monolithic Script / Untyped Application**:
   - *Pros*: Fastest to write for an initial demo.
   - *Cons*: Rapid technical debt, fragile spaghetti code, inability to cleanly decouple simulation from real business logic, difficult automated testing.
   - *Verdict*: Rejected in favor of structured modularity.

3. **Cloud-Native Serverless (AWS Lambda / DynamoDB)**:
   - *Pros*: Managed infrastructure, automatic scaling.
   - *Cons*: Violates the constraint of avoiding paid cloud dependencies; creates vendor lock-in; impedes seamless local offline development and testing.
   - *Verdict*: Rejected to maintain independence and complete local reproducibility.

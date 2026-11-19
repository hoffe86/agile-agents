# ADR 0006 — Record each run in a structured, append-only event stream

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H6)
- **Related:** ADR 0003 (verification gates), ADR 0004 (resource budgets)

## Context

Human-readable hand-offs support coordination but do not provide a reliable
audit trail for run ordering, gate outcomes, or resource usage. Run evidence
must remain usable after a process interruption and accessible without a
central collection service.

## Decision

Record run-level events in an append-only JSONL stream with one designated run
coordinator responsible for event emission. Use
observability conventions where they improve interoperability, without
requiring an external collector.

## Consequences

- Events remain inspectable and ordered within a run, including after
  interruption.
- Centralized emission avoids concurrent-writer coordination and keeps
  worker-reported telemetry from becoming the audit source.
- The stream does not capture every internal worker event; adding that
  granularity would require a separate decision.

## Alternatives considered

- **Have every worker write to a shared run log.** Rejected: concurrent writes
  and ordering would require additional coordination.
- **Rewrite one aggregate document after each event.** Rejected: it is less
  resilient to interruption and less suitable for append-only execution.
- **Require a telemetry collector.** Rejected: it adds infrastructure to
  workflows that should work locally.

## References

- `plugins/agile-agents-core/skills/run-event-log/`
- OpenTelemetry semantic conventions

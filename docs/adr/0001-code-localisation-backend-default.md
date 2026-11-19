# ADR 0001 — Select a local-first code-localisation strategy

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H1)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md`

## Context

Engineering work benefits from identifying relevant repository areas before
making changes. Projects differ in available infrastructure, privacy
constraints, and repository size, so the harness needs a useful default that
does not depend on external services.

## Decision

Use local structural analysis as the dependable fallback for code localisation.
Projects may opt into semantic or service-backed retrieval when those
capabilities are available and appropriate. External infrastructure is never
required for the default path.

## Consequences

- Local and restricted environments can use the harness without credentials or
  additional services.
- Projects with richer retrieval infrastructure can use it without changing
  the underlying workflow.
- A local fallback may provide less semantic recall, and optional retrieval
  paths add maintenance cost.

## Alternatives considered

- **Require an external semantic service.** Rejected: it would make setup,
  credentials, and network access prerequisites for ordinary use.
- **Support only one retrieval approach.** Rejected: it would either impose
  unnecessary infrastructure or prevent projects from using capabilities they
  already operate.

## References

- `docs/research/autonomous-coding-agents-2026.md`
- `plugins/agile-agents-core/skills/code-localisation/`

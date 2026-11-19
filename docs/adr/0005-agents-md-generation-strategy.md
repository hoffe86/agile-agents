# ADR 0005 — Generate portable agent guidance from the structured solution profile

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H5)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md`

## Context

Portable agent guidance needs to be understandable to tools that do not consume
the harness's structured configuration. Maintaining both a machine-readable
profile and a separate hand-written narrative would create competing sources
of operational truth.

## Decision

Treat the structured solution profile as the source of truth and generate the
portable guidance from it. The generated document is a readable projection,
not an independently maintained configuration.

## Consequences

- Solutions maintain operational facts in one authoritative place while still
  providing a portable narrative for other tools.
- The generator and its output must remain consistent with the profile.
- Generated guidance may not express every profile detail; consumers needing
  machine-readable facts must use the profile itself.

## Alternatives considered

- **Hand-maintain both documents.** Rejected: their content would drift.
- **Keep only the portable narrative.** Rejected: it cannot provide the
  structured validation and reliable machine consumption needed by the
  harness.
- **Generate only a pointer to the profile.** Rejected: it would not provide
  useful context to tools that do not understand the profile.

## References

- `docs/research/autonomous-coding-agents-2026.md`
- `plugins/agile-agents-core/skills/solution-profile-interview/`

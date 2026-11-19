# ADR 0010 — Separate review coordination from independent review

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (review-topology split)
- **Related:** ADR 0009 (author ownership and independent verification), ADR 0007 (advisory capability intent), ADR 0011 (distinct actor and capability names)

## Context

Review coordination and line-by-line quality assessment are distinct kinds of
work. Combining them can reduce the depth of review as changes grow, serialize
work that could be independent, and make general review difficult to request
without invoking the full review process.

## Decision

Separate review coordination from independent review lenses. The coordinator
selects applicable lenses, reconciles overlapping findings, and produces one
verdict; each lens assesses its own domain without taking over coordination.

## Consequences

- Independent assessments can run concurrently and be requested separately.
- Coordination no longer competes with detailed review for the same attention.
- Reconciliation and deduplication become explicit responsibilities, and
  multiple lenses may report the same underlying issue.

## Alternatives considered

- **Keep coordination and general review in one role.** Rejected: detailed
  review can be crowded out by coordination work.
- **Have the run coordinator dispatch and merge every lens directly.**
  Rejected: it removes a focused owner for review triage and reconciliation.
- **Combine independent lenses into one general assessment.** Rejected: it
  reduces the independent scrutiny that the review structure is intended to
  provide.

## References

- ADR 0009 — task authorship and independent checks
- `plugins/agile-agents-core/agents/` — current review responsibilities

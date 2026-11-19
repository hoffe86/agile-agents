# ADR 0002 — Combine external comparability with representative internal evaluation

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H2)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md`

## Context

The harness needs repeatable evidence that improvements help both on established
software-engineering tasks and on the kinds of constraints its users encounter.
A single source cannot provide both broad comparability and sufficient
representation of the harness's target work.

## Decision

Maintain a versioned evaluation corpus that combines an established external
benchmark with representative, internally curated tasks. Keep the two sources
distinct in reporting so comparable results are not confused with
solution-specific evidence.

## Consequences

- Results can be compared with external baselines while still exercising
  relevant engineering constraints.
- Internal curation and benchmark maintenance add ongoing work.
- Small or changing samples limit the strength and generalisability of
  conclusions; report uncertainty and avoid treating scores as universal.

## Alternatives considered

- **Use only an external benchmark.** Rejected: it may not represent the
  constraints that matter to the harness's users.
- **Use only internal tasks.** Rejected: it removes external comparability and
  risks overfitting evaluation to local expectations.

## References

- `docs/research/autonomous-coding-agents-2026.md`
- `eval/README.md`
- SWE-bench Verified: <https://www.swebench.com/verified.html>

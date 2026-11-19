# ADR 0003 — Verify changes deterministically before independent review

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H3)
- **Related:** ADR 0004 (run-level resource controls), ADR 0006 (run evidence), ADR 0009 (task authorship; verification gate unchanged)

## Context

Independent review is a high-value but comparatively expensive judgement step.
It should assess changes that have already passed the applicable deterministic
quality checks, rather than spending reviewer effort diagnosing failures those
checks can identify directly.

## Decision

Run the configured deterministic quality gate after implementation and before
independent review. The gate is fail-fast, uses the solution's declared
verification commands, and allows only bounded corrective attempts; it stops
early when attempts do not make progress.

## Consequences

- Review begins with evidence that the change meets its configured build and
  test bar.
- A non-converging change stops for human direction instead of consuming
  unbounded effort.
- Projects must maintain valid verification configuration, and the gate adds
  time before review.

## Amendment (2026-08) — allow bounded convergence attempts

The correction policy was revised to permit additional attempts for
deterministic failures, while stopping early when the work does not converge.
The exact retry budget is maintained with the verification procedure.

## Alternatives considered

- **Review before deterministic checks.** Rejected: reviewers would spend time
  on defects that automated checks can detect consistently.
- **Allow unbounded correction loops.** Rejected: they can consume resources
  without improving the change.
- **Skip the gate when project verification is unknown.** Rejected: an
  unverified change must not be presented as verified.

## References

- ADR 0004 — run-level resource controls
- `plugins/agile-agents-core/skills/test-bar-gate/`

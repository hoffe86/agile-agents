# ADR 0004 — Enforce a per-run resource budget and stop on breach by default

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H4)
- **Related:** ADR 0003 (bounded verification), ADR 0006 (run evidence)

## Context

An autonomous run can consume resources through retries, repeated review, or
non-converging work. Application operating costs and the resources consumed by
one engineering run are different concerns; the latter needs a bound that can
be enforced during execution.

## Decision

Apply a solution-defined budget to measured per-run resource usage. When an
enforced budget is exceeded, stop the run and request human direction by
default. Report resource dimensions that cannot be reliably measured as
unmetered or informational, not as zero.

## Consequences

- A stalled run cannot silently consume an unbounded share of the project's
  budget.
- Large or unexpectedly complex work may require human approval or a narrower
  follow-up.
- Resource telemetry and budget configuration must be maintained; no budget
  can bound dimensions the runtime does not measure.

## Amendment (2026-08) — base enforcement on measured usage

The budget now applies only to resource dimensions supported by runtime
telemetry. An unavailable monetary rate is reported as unmetered, not as zero,
and elapsed time is not inferred from overlapping call durations.

## Alternatives considered

- **Reuse the application's operating-cost budget.** Rejected: it measures a
  different workload and cannot reliably bound one engineering run.
- **Use only one resource measure.** Rejected: a run can consume heavily in a
  dimension that a single measure does not capture.
- **Warn but continue by default.** Rejected: it leaves the non-converging run
  that motivated this decision free to continue.

## References

- `plugins/agile-agents-core/skills/cost-budget/`
- `plugins/agile-agents-core/skills/cost-budget/references/tier-defaults.md`

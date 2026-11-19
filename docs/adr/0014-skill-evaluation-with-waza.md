# ADR 0014 — Evaluate reusable agent capabilities separately from whole runs

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (skill quality measurement)
- **Related:** ADR 0008 (layered evaluation), ADR 0002 (evaluation corpus)

## Context

Whole-run evaluation cannot isolate whether a reusable capability is selected
appropriately or improves the work that uses it. Skill quality therefore needs
its own evaluation unit and evidence, complementary to pipeline evaluation.

## Decision

Use Waza to evaluate reusable skills as a distinct layer alongside whole-run
evaluation. Prefer offline, deterministic checks for structural validity and
routing signals; treat observed invocation and efficacy as separate questions
that require their own evidence. Keep evaluation definitions portable enough
to replace the runner if needed.

## Consequences

- Skill defects can be found without requiring a complete pipeline run.
- Structural or heuristic checks are proxies; they cannot establish actual
  runtime selection or effectiveness by themselves.
- The evaluation layer depends on an external tool whose behavior and
  availability must be maintained.

## Alternatives considered

- **Evaluate skills only through end-to-end outcomes.** Rejected: outcomes do
  not isolate skill selection or contribution.
- **Build and maintain all evaluation machinery in-house.** Rejected:
  established tooling can provide useful skill-oriented evaluation with less
  custom infrastructure.
- **Treat heuristic routing scores as proof of runtime behavior.** Rejected:
  actual invocation and effectiveness require separate evidence.

## References

- ADR 0008 — layered evaluation strategy
- ADR 0015 — pipeline evaluation
- `.waza.yaml`
- `eval/README.md`

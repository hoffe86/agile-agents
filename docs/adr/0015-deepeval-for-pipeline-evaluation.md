# ADR 0015 — Use DeepEval to score recorded pipeline traces

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (pipeline evaluation tooling)
- **Related:** ADR 0014 (skill evaluation), ADR 0008 (layered evaluation)

## Context

The harness needs evidence about behavior recorded during pipeline runs, while
skill quality is a separate evaluation concern. A scorer must distinguish
recorded trace evidence from claims about whether a skill was used correctly
or whether the delivered work was successful.

## Decision

Use DeepEval as an offline scorer for existing pipeline traces and retain
Waza for skill evaluation. The pipeline scorer measures recorded skill
invocation evidence only; it does not drive runs, establish correct skill use,
or grade delivered outcomes. Keep the evaluation definitions distinct from the
runner, and do not transmit repository content to an external service as part
of offline scoring.

## Consequences

- Recorded pipeline behavior can be scored without conflating it with skill
  quality or task success.
- A trace score depends on the completeness and provenance of the supplied
  trace; it is not proof of runtime authenticity or outcome quality.
- The framework and trace adapter add dependency and schema-maintenance risk.
- End-to-end outcome evaluation remains a distinct capability and must not be
  claimed from this scorer's results.

## Amendment (2026-11) — narrow pipeline scoring to recorded traces

The active pipeline-scoring scope is recorded skill-invocation evidence only.
It does not establish successful invocation, correct capability use, or task
outcome quality. The current evaluation documentation defines the active
scoring contract.

## Alternatives considered

- **Use the skill-evaluation runner for pipeline trace scoring as well.**
  Rejected: the evaluation units and evidence needs differ.
- **Use only a custom trace scorer.** Rejected: it would duplicate evaluation
  framework functionality; the integration remains replaceable if the fit
  changes.

## References

- ADR 0008 — layered evaluation strategy
- ADR 0014 — skill evaluation
- `eval/README.md`

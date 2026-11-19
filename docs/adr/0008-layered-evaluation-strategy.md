# ADR 0008 — Evaluate process conformance, review quality, and outcomes separately

- **Status:** Accepted
- **Date:** 2026-06
- **Deciders:** Eval harness hardening (follow-on to ADR 0002 self-benchmarking composition)
- **Related:** ADR 0002 (evaluation corpus), ADR 0003 (deterministic gates), ADR 0004 (resource budgets), ADR 0006 (run evidence)
- **Extended by:** ADR 0014 (skill evaluation), ADR 0015 (pipeline evaluation)

## Context

An end-to-end outcome score cannot show whether a failure came from process
conformance, review quality, or the delivered result. Conversely, process
conformance alone cannot establish that the result is correct. The evaluation
approach needs distinct evidence for these different questions.

## Decision

Structure evaluation around distinct questions: process conformance, review
detection, and delivered outcomes. These objectives require complementary
evidence and must not be conflated. Evaluate reusable capabilities, such as
skills, separately because they are a different unit of evaluation. A layer is
not evidence of a current capability until it is implemented and verified.

## Consequences

- Failures can be attributed to different parts of the system, with cheaper
  checks used more frequently than full-run evaluation.
- A conforming process can still produce poor work, and outcome evaluation
  alone cannot prove process quality; the layers are complementary.
- Some quality dimensions require labelled examples or human judgement and
  remain more expensive to evaluate.

## Alternatives considered

- **Use only end-to-end outcome evaluation.** Rejected: it cannot diagnose
  process failures and is too costly for frequent gating.
- **Evaluate every dimension with one deterministic suite.** Rejected: review
  quality and outcome quality cannot both be established by the same
  deterministic evidence.
- **Treat skill evaluation as another whole-run layer.** Rejected: it evaluates
  a different unit and requires separate evidence.

## References

- ADR 0002 — evaluation corpus
- ADR 0014 — skill evaluation
- ADR 0015 — pipeline evaluation

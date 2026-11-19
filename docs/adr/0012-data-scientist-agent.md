# ADR 0012 — Treat data analysis as a distinct engineering capability

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (roster extension)
- **Related:** ADR 0009 (author verification), ADR 0010 (independent review), ADR 0007 (capability intent)

## Context

Data work often delivers a conclusion rather than a software feature. Its
validity depends on methods such as suitable baselines, sound evaluation,
uncertainty, leakage control, provenance, and fairness. Ordinary software
quality checks alone cannot establish that an analytical conclusion is
supported.

## Decision

Treat data analysis as a distinct capability with discipline-specific
authoring guidance and independent evaluation. Apply shared data-engineering
practices to pipeline work, with engineering responsibilities assigned along
the relevant technical boundaries. An analytical task may validly conclude
that evidence is inconclusive or does not support the hypothesis; those
outcomes must be judged by the quality of their evidence, not by whether they
are positive.

Keep analysis, data-platform engineering, and application behavior distinct
where they require different evidence, joining them through explicit
task-level contracts.

## Consequences

- Analytical conclusions receive methods-appropriate evaluation instead of
  being treated as ordinary feature implementation.
- Negative and inconclusive results can prevent downstream work from relying
  on an unsupported premise.
- Separate responsibilities require coordination and explicit hand-offs when
  work crosses analytical, platform, or application concerns.
- Results that lack reproducible evidence cannot be independently verified.

## Alternatives considered

- **Route analytical work through ordinary application engineering alone.**
  Rejected: build and test success do not establish statistical validity.
- **Combine analysis, platform, and application work into one undifferentiated
  task.** Rejected: the evidence and ownership boundaries become unclear.
- **Require analytical work to produce a positive result.** Rejected: it would
  bias the process toward unsupported conclusions.

## References

- ADR 0009 — author-owned verification with independent checks
- ADR 0010 — independent review responsibilities
- `plugins/agile-agents-core/skills/data-science-practices/`
- `plugins/agile-agents-core/skills/data-engineering-practices/`

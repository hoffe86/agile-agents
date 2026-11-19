# ADR 0016 — Research and Plan draw on contributing specialists (T-shaped team)

- **Status:** Accepted
- **Date:** 2026-11
- **Deciders:** Harness maintainers (pipeline shape), on explicit request of the repository owner
- **Related:** ADR 0009 (authors own their tests), ADR 0010 (independent review lenses), ADR 0012 (data capability), ADR 0013 (senior judgement), ADR 0004 (cost envelope), ADR 0006 (run event log), ADR 0015 (pipeline evaluation)

## Context

When Research and Plan draw on limited specialist input, important constraints
and risks may surface only during implementation or review, leading to rework
or a stop. A T-shaped team combines depth in each discipline with broad
participation in shared refinement, bringing those perspectives into the plan
before work begins.

## Decision

All available, eligible contributing specialists participate in Research and
Plan refinement. Their read-only contributions surface domain constraints,
approaches, verification needs and risks before implementation. Substantive
feedback informs the plan, and unresolved disagreement is presented for human
plan approval.

Contributions inform decisions but do not replace human approval or independent
review of delivered work. Existing design gates and sequential implementation
remain unchanged.

This refines ADR 0012 rather than superseding it: data perspectives inform
Research and Plan, while data analysis remains implementation work.

## Consequences

- Broader input surfaces constraints and risks before approval, reducing the
  likelihood of costly corrections later.
- Participation increases coordination and resource cost during Research and
  Plan; the existing cost envelope still applies.

## Alternatives considered

- **Consult specialist perspectives only when implementation begins.** Rejected:
  constraints would surface after the plan is approved, when they are more
  expensive to address.
- **Rely on independent review to discover missing perspectives.** Rejected:
  review remains essential, but discovering basic domain constraints there
  creates avoidable rework.

## References

- ADR 0012 — data analysis as a distinct engineering capability
- `docs/flow/research.md`
- `docs/flow/plan.md`

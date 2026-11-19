# ADR 0013 — Use shared engineering judgement without weakening controls

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (agent authoring posture)
- **Related:** ADR 0009 (author verification), ADR 0010 (independent review), ADR 0012 (data capability), ADR 0004 (run-level resource controls)

## Context

Rigid procedures and scattered prohibitions can cause agents to ask unnecessary
questions or follow steps without understanding the decision. Greater
autonomy, however, must not remove human authority, verification, or safety
controls.

## Decision

Provide shared engineering-judgement principles and apply them to each
responsibility's domain. Agents should resolve ordinary, reversible uncertainty
within scope and surface consequential assumptions at an actionable human
gate. Autonomy changes how decisions are made; it does not relax approvals,
verification, scope boundaries, or independent review.

## Consequences

- Work can proceed through routine uncertainty without unnecessary
  interruptions.
- Consequential decisions become visible where a human can still act on them.
- Judgement cannot be completely enforced by static checks, so behavior and
  decision evidence require ongoing evaluation.
- More autonomous decisions can be wrong; human gates and independent checks
  remain necessary.

## Alternatives considered

- **Keep all decisions as prescribed procedures.** Rejected: procedures cannot
  cover every context and can create contradictory instructions.
- **Relax gates along with increasing autonomy.** Rejected: it conflates
  decision-making discretion with authority to bypass controls.
- **Duplicate judgement rules in every responsibility definition.** Rejected:
  copies would drift and be difficult to correct consistently.

## References

- `plugins/agile-agents-core/skills/engineering-judgement/`
- `plugins/agile-agents-core/skills/read-repo-context/`

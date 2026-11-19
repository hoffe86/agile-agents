# ADR 0011 — Distinguish review actors from review capabilities

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (review-roster naming)
- **Related:** ADR 0010 (review responsibility boundaries), ADR 0006 (run evidence), ADR 0007 (advisory capability intent)

## Context

The harness exposes both named actors and reusable capabilities. When the same
name refers to both, readers and automated reference checks cannot reliably
tell whether a document means to invoke an actor or use a capability.

## Decision

Use distinct, consistent names for review actors and review capabilities.
Naming must communicate whether an item performs review work or provides
reusable review guidance, and the convention should apply consistently across
the review structure.

## Consequences

- References are clearer to people and more reliably validated by tooling.
- Renaming a public actor can affect downstream consumers, so compatibility
  impact must be considered when changing names.
- Current names remain defined by the harness's agent and skill manifests,
  rather than duplicated in this architectural rule.

## Alternatives considered

- **Allow an actor and capability to share a name.** Rejected: references
  become ambiguous and validation can miss broken links.
- **Maintain exceptions for each collision.** Rejected: exception lists are
  fragile and do not give future additions a consistent convention.

## References

- ADR 0010 — separation of review responsibilities
- `plugins/agile-agents-core/agents/`
- `plugins/agile-agents-core/skills/`

---
name: research
description: >-
  Research phase of Research → Plan → Implement, usable by any agent: verify a
  prepared concept, decisions, codebase and external facts; size research
  depth; separate evidence from assumptions; surface data feasibility without
  analysing data; gather read-only contributions from every available author
  discipline. States the phase purpose, outcome, rules, quality bar and
  exit gates. An orchestrator such as dev-lead keeps transitions, approvals,
  stops and retry budgets.
metadata:
  applies_to: all
---

# Research phase

## Purpose

Establish what is true before anyone plans or builds: the prepared direction
holds, the facts it relies on are verified, and every remaining uncertainty is
named. Research verifies; it does not design from scratch, decide for the
human, or implement.

Typical users: `dev-lead` (Stage 1), the author specialists contributing to
its breadth round, `architect` (delegated depth) and any agent asked to check
a direction before work starts.

Research is T-shaped, like a scrum team: every available author discipline
contributes breadth from its own depth, so domain constraints and likely
review findings surface before planning rather than after implementation.

## Outcome

A research result the next phase can plan from:

- verified facts, each with its source;
- assumptions, each with its impact;
- the component, data or interface contract the work will use;
- named NFRs and security posture;
- trade-offs, open risks, decision gaps and data questions;
- each consulted discipline's impact, constraints, verification approach and
  likely review findings, or its recorded `none`;
- the approach-invalidating risk to sequence first, if any.

## Rules

- Start from the prepared concept and accepted decisions, the profile and the
  existing code. Conform to the declared `documentation.framework`.
- Never author an ADR or a replacement design. Surface an uncaptured material
  decision as a gap for the human.
- Never present a guess as a fact. An unverified service, limit, quota, price,
  API shape or capability is an assumption.
- Research does not analyse data or build models.
- Stay read-only: no source, test, IaC or tracker changes.

## Quality bar

- Every load-bearing fact is sourced or labelled as an assumption.
- Depth matches blast radius: no deep study of a local change, and no
  lightweight pass over a new boundary.
- The result fits on one page, so the human can read it at plan approval.

## Exit gates

The phase is complete only when all hold:

1. Each decision is captured in an accepted record, design/work-item decision
   or the result's decision section. A project without ADRs does not fail this.
2. Every decision gap is either resolved by a human or listed for approval.
3. A concrete contract exists for tasks to reference.
4. NFRs and security posture are named, not "TBD".
5. No silent assumptions remain.
6. A missing required data source or unpermitted personal data is raised as
   a blocker now, not later.
7. Every available author discipline contributed, or its skip is recorded
   with the reason (inactive, disabled or unavailable).

The caller enforces these gates. Under `dev-lead`, `dev-lead` alone owns stage
transitions, corrective retries and the decision to enter Plan.

## Working method

Breadth always comes first. Consult every available author specialist —
`architect`, `coding`, `infrastructure` and, with `data_science.enabled`,
`data-scientist` — in parallel and read-only. Each answers with
`RESEARCH CONTRIBUTION COMPLETE` (`Mode: research`) from its own discipline:
existing code and patterns, platform and deployment constraints, data
availability, how it would verify the work, and what its reviewer would flag
later. A discipline with nothing at stake answers `Impact on my domain: none`
briefly; never pad a contribution.

Choose research depth proportionately:

- Keep it lightweight when the change is local, touches roughly fewer than
  three files, adds no boundary, contract, dependency or cloud resource, has no
  material trade-off, and is covered by existing decisions.
- Use `architect` depth when a boundary, contract, dependency, cloud resource,
  material trade-off or possible decision gap needs architectural judgement;
  it synthesises the contributions into its design.
- For a data requirement with `data_science.enabled`, check data existence,
  permitted use, fitness for purpose, contract, physical landing and the
  questions analysis must answer.

Verify load-bearing external facts with applicable authoritative sources and
record the source, on the lightweight path as well as the delegated one. If a
fact cannot be verified, label it as an assumption, state its impact, and
carry it forward. A question that needs analysis becomes an explicit
`data-scientist` feasibility task in Plan, sequenced before dependent work.

Contributions inform; they do not decide. Reconcile conflicting contributions
explicitly and carry unresolved dissent to plan approval. Reviewers do not
contribute: their independence at review is the point. Carry facts,
assumptions, trade-offs, risks, decision gaps, data questions, contributions
and consequential calls into Plan. Under `dev-lead`, use `dev-lead-templates` for
the Research payload and reporting recipe.

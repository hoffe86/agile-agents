---
name: implement
description: >-
  Implement phase of Research → Plan → Implement, usable by any author or
  orchestrator: deliver approved tasks one at a time with the tests that cover
  them, route each deliverable to the right author, record reviewable evidence
  and prepare for the deterministic test bar. States the phase purpose,
  outcome, rules, quality bar and exit gates. An orchestrator such as dev-lead
  keeps approvals, sequencing, gates, stops and retry budgets.
metadata:
  applies_to: all
---

# Implement phase

## Purpose

Deliver exactly the approved plan, task by task, with proof that it works.
Implement changes code, tests and IaC; it does not change the plan, approve
its own work, or review itself.

Typical users: `dev-lead` (Stages 6–7, direct or delegated), `coding`,
`infrastructure` and `data-scientist`.

## Outcome

For each approved task:

- the change, inside the approved scope and locked design;
- tests or IaC validation covering every added or changed behavior;
- a behavior-to-test mapping;
- `Existing tests modified`: `none`, or what each old assertion claimed and
  why that claim was invalid;
- open constraints and questions for review.

## Rules

- Start only after plan approval, and design approval when required.
- Do not add a dependency, boundary, contract or cloud resource that was not
  approved; stop and report instead.
- Keep one implementation writer active at a time, in dependency order.
- Authors own their tests. Fix production code to pass; must never weaken,
  delete, skip or rebaseline a test.
- No drive-by changes; follow-ups are reported, not built.
- Human-only operations stay human-only: merge, force-push, production deploy.

## Quality bar

- Load `development-practices` and `testing-practices` for application work,
  plus `iac-best-practices` for IaC, and applicable solution guidance.
- Test owned behavior, not third-party library internals.
- The smallest correct change; existing patterns before new abstractions.

## Exit gates

1. Per task: build green, the task's tests pass, every behavior names its test,
   test changes are justified, and acceptance criteria match the change.
2. Combined: the combined-diff `test-bar-gate` passes (lint, typecheck, unit,
   smoke as configured), plus any profile-enabled deploy check.
3. Independent review follows; the author never reviews its own work.

The caller enforces these gates. Under `dev-lead`, `dev-lead` remains
authoritative for approval, sequencing, the deterministic gate, retries and
entry to Review. This skill does not authorize skips, retries, approval changes,
or reviewer dispatch.

## Working method

Choose separately for each approved task, only after Stage 4 approval and any
applicable Stage 5 design approval when `dev-lead` orchestrates:

- Use direct `dev-lead` authorship when the task fits its capability inside the
  approved scope. It then owns application code and tests, or IaC and its IaC
  tests/validation.
- Delegate application behavior to `coding`; deployment, pipeline or
  infrastructure deliverables and their IaC tests to `infrastructure`.
- Analysis, profiling, experiments, trained models and evaluation evidence belong
  to `data-scientist`, never direct `dev-lead` work or an application/IaC
  author. `coding` owns the application that serves a model; pass the analysis
  `Interface for coding` to the next task. If data science is disabled or
  unavailable, raise the scope/capability question to the orchestrator.

Send each author only that task's acceptance criteria, approach note and
locked-design constraints. Under `dev-lead`, use the dispatch and ready-set
recipe in `dev-lead-templates`.

Delegated work returns its canonical hand-off, one per task. Direct `dev-lead`
work records the same evidence in the task's session record as
supervisor-owned evidence: never invent a worker identity, sentinel or
`handoff_received` event. Carry all task evidence into the combined-diff review.

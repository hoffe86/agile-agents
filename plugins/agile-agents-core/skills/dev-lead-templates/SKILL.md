---
name: dev-lead-templates
description: Stage-local preparation, SQL/tracker bookkeeping and reporting recipes for dev-lead, plus plan/design approval prompts and the final Done/Stop report. Read only the named section on stage entry or resume; load other references only as needed. The supervisor owns transitions, gates, stop conditions, retry budgets and event/cost semantics; these recipes supply inputs and output shapes, not alternate control flow. Not used by other agents.
applies_to: all
---

# dev-lead-templates

The `dev-lead` agent owns **all control flow**: delegates, entry/exit gates, stops,
approval handling, persistent retry counters, permissions and event/cost semantics.
This skill supplies stage-local recipes and output shapes. Prompts return the
human's answer to the supervisor; they do not decide the next stage.

## When to load

| Section | Read at entry/resume | Reference |
|---|---|---|
| Stage 0 | Intake preparation | [Stage 0](references/intake-plan.md#stage-0) |
| Stage 1 | Research preparation/reporting | [Stage 1](references/intake-plan.md#stage-1) |
| Stage 2 | Decomposition and SQL cache | [Stage 2](references/intake-plan.md#stage-2) |
| Stage 3 | Tracker creation payload | [Stage 3](references/intake-plan.md#stage-3) |
| Prompt | Stage 4 — plan approval | [Prompt](references/plan-approval.md#prompt) |
| Prompt | Stage 5 — conditional design approval | [Prompt](references/design-approval.md#prompt) |
| Stage 6 | Task dispatch preparation | [Stage 6](references/implementation-review.md#stage-6) |
| Stage 7 | Deterministic gate preparation | [Stage 7](references/implementation-review.md#stage-7) |
| Stage 8 | Review payload and ledger SQL | [Stage 8](references/implementation-review.md#stage-8) |
| Stage 9 | Completion evidence and artifacts | [Stage 9](references/completion.md#stage-9) |

When rendering a final report (including an early stop), also read
[Report](references/done-report.md#report). For tracker transitions or provisional
cleanup, read [Tracker mechanics](references/intake-plan.md#tracker-mechanics).
Other skill references (such as cost or gate commands) are loaded only as needed.

Resolve all paths relative to **this loaded skill's home**, not the consumer
repository's working directory. Read only the exact named level-two section,
including its subheadings; do not preload all sections or files. Missing file or
missing/mismatched section: stop and surface malformed contract/context, never
reconstruct a recipe or bypass the supervisor's gate.

## Rules that apply to every template

- **Fill every placeholder.** A rendered template still containing `<...>` is a
  malformed hand-off — treat it the way you would treat a worker's malformed
  sentinel block.
- **Never invent content to fill a placeholder.** If a field has no source (no
  trade-off was surfaced, no ADR applies), write `none` explicitly rather than
  fabricating one.
- **Do not restructure.** Humans and downstream tooling read these by section
  heading; renaming or reordering sections breaks that.
- **Summarise, never paste.** Intermediate worker output is linked or condensed to
  one line — the reader's question is "is this done, and if not why".

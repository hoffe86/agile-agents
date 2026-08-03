---
name: dev-lead-templates
description: Rendering templates for the dev-lead orchestration run — the plan-approval gate prompt (Stage 1.7), the conditional design-approval gate prompt (Stage 2.5), and the final Done/Stop report (Stage 6). Load only at the moment a template is needed; the dev-lead agent definition carries the decision logic, this skill carries the markdown shapes. Not used by any other agent.
applies_to: all
---

# dev-lead-templates

The `dev-lead` agent owns *when* to render these and *what* the choices mean. This
skill owns only the **shape of the output**, so the agent definition stays about
decisions rather than markdown.

## When to load

| Template | Load at | Reference |
|---|---|---|
| Plan approval (`ask_user`) | Stage 1.7 — after `backlog-manager` emitted `TASKS PLANNED` | [`references/plan-approval.md`](references/plan-approval.md) |
| Design approval (`ask_user`) | Stage 2.5 — only when the conditional trigger fires | [`references/design-approval.md`](references/design-approval.md) |
| Final report | Stage 6 — Done, Blocked, or Stopped | [`references/done-report.md`](references/done-report.md) |

Do not load all three up-front. Each is a leaf template with no cross-dependency.

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

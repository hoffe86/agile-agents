# Design-approval prompt (dev-lead Stage 2.5, conditional)

Fires **after** the mandatory plan approval and **before** coding — only when
Research surfaced something the human should sign off on separately from the task
plan.

**Choices:** `Approve and continue` / `Adjust design` / `Stop`.

```markdown
## Architect proposed: <decision title(s) — captured inline in arc42 §9; binding ADR ids if any apply>

**<decision title>**
- Chose: <X>
- Over: <Y>
- Cost: <what we give up>
- Revisit if: <trigger>

<repeat block per significant decision>

**New external dependencies / services / boundaries introduced:** <list or "none">
**ADRs honoured (existing, binding):** <list of ADR ids, or "none applicable">
**ADR gaps (need human ADR authoring before coding):** <list with one-line summary per gap, or "none">

> If any ADR gaps are listed, please author the ADR(s) yourself (no agent will
> create them) and re-run, or explicitly waive each gap below.

Coding will be locked to this design. Approve to proceed?
```

## Handling the answer

- **Approve** → proceed to Stage 3 and continue autonomously.
- **Adjust** → send `architect` the human's feedback as a corrective message
  (counts as the architect stage's one corrective retry); re-render this template
  with the revised design. **Cap: one Adjust round per run** — a second Adjust on
  the same architect output is not allowed. If the human is still not satisfied,
  choose Stop (the requirement needs rewording or a new run), not another loop.
- **Stop** → mark remaining todos `blocked` with reason "user stopped at design
  gate" and finish with the Stop report.

# Design-approval prompt (dev-lead Stage 5, conditional)

## Prompt

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
**Decision gaps (need a human decision before coding):** <list with one-line summary per gap, or "none">

> If any decision gaps are listed, please settle each one yourself — as an ADR
> if this project uses ADRs, otherwise in the design doc or work item (no agent
> creates ADR files) — and re-run, or explicitly waive each gap below.

Coding will be locked to this design. Approve to proceed?
```

### Return the answer

Return the selected choice and feedback unchanged to `dev-lead`. Its Stage 5 owns
approval, design adjustment accounting and stopping. This rendering template
authorises no transition and sets no corrective budget.

# Acceptance criteria — task-05

1. **Title present** — first line is a single imperative sentence ≤ 72 characters, no
   trailing period.
2. **Five sections present** — exactly the headings `## What`, `## Why`, `## How`,
   `## Testing`, `## Risk & rollback` in that order.
3. **JIRA reference** — `JIRA-4421` appears at least once and is hyperlinked or in inline
   code formatting.
4. **Behaviour, not syntax** — the `## What` and `## Why` sections describe the user-facing
   change (cancellation rules), not file paths or method signatures. A reviewer who never
   opens the diff understands the change.
5. **Risk section concrete** — `## Risk & rollback` either lists at least one specific risk
   with mitigation, or states "no migration; revert by reverting the commit" explicitly
   (not left empty or generic).

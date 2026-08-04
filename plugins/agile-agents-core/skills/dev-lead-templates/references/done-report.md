# Final Done / Stop report (dev-lead Stage 10)

Return **only** this report. Do not paste the full intermediate output of each
stage — link or summarise. The reader's question is "is this done, and if not
why" — answer that first.

```markdown
# Dev Lead Report: <requirement title>

**Status:** ✅ Done | 🟡 Blocked (awaiting human) | ❌ Stopped (failure)
**Definition of Done:** <one sentence from Intake>

## Stages run
| Stage | Agent | Outcome |
|---|---|---|
| Architect | architect | ✅ <chose X, honours ADR-NNN> | ⏭ skipped (<reason>) |
| Coding | coding | ✅ <N files, build green> |
| Testing | testing | ✅ <M tests added, all pass> |
| Review | review | ✅ Approve | 🔁 Request changes (looped once) |

## What was delivered
- <observable behaviours, mapped to the Definition of Done>

## Trade-offs (consolidated)
- **Architect:** <chose X over Y because… cost… revisit if…>
- **Coding:** <…>
- **Infrastructure:** <…>

## Follow-ups (NOT done in this run, by design)
- <out-of-scope items raised by any stage>

## Open questions for the human
- <only if Status is 🟡 Blocked>

## Failure trace (if Status is ❌)
- Stage: <which>
- Gate that failed: <which>
- Corrective retry sent: <verbatim>
- Result: <verbatim>
- Recommended next action: <concrete>
```

## Rules

- **Trade-offs are consolidated, never invented** — only what stages actually
  surfaced. An empty section says `none surfaced`.
- **Report honestly.** Shrunk scope, a degraded quality bar, or an accepted risk
  goes here in plain language — first, not buried under Follow-ups.
- **A cost warning from `cost-budget` (≥80% of an envelope) is reported even on a
  ✅ Done** run.
- Status is ✅ Done only when every Definition-of-Done item in the agent
  definition is true. If any is false, say so plainly.

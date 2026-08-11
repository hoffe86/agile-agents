# Final Done / Stop report (dev-lead Stage 10)

Return **only** this report. Do not paste the full intermediate output of each
stage — link or summarise. The reader's question is "is this done, and if not
why" — answer that first.

```markdown
# Dev Lead Report: <requirement title>

**Status:** ✅ Done | 🟡 Blocked (awaiting human) | ❌ Stopped (failure)
**Definition of Done:** <one sentence from Intake>

## Stages run
| Stage | Agent | Outcome | Tokens (in/out) | AIU |
|---|---|---|---|---|
| Architect | architect | ✅ <chose X, honours ADR-NNN> | ⏭ skipped (<reason>) | <in>/<out> | <aiu> |
| Coding | coding | ✅ <N files, build green> | <in>/<out> | <aiu> |
| Testing | testing | ✅ <M tests added, all pass> | <in>/<out> | <aiu> |
| Review | review | ✅ Approve | 🔁 Request changes (looped once) | <in>/<out> | <aiu> |
| **Run total** | | | **<in>/<out>** | **<aiu>** |

Usage columns come from `collect-usage.py` (`by_phase`). Report `<n/a — telemetry
unavailable>` across the row if it exited 3; never write `0` or a guess, and never write a
USD figure unless `cost_envelope.usd_per_aiu` is set — an invented number here is worse
than a blank, because it looks like a measurement.

## What was delivered
- <observable behaviours, mapped to the Definition of Done>

## Requirement coverage
| # | Acceptance criterion | Delivered by | Evidence | Status |
|---|---|---|---|---|
| ac-1 | <verbatim from the requirement> | <task id + title> | <test name / review finding> | ✅ covered |
| ac-2 | <verbatim from the requirement> | — | — | ⚠️ out of scope (<reason agreed at Stage 2>) |
| ac-3 | <verbatim from the requirement> | <task, blocked> | — | ❌ not covered |

## Trade-offs (consolidated)
- **Architect:** <chose X over Y because… cost… revisit if…>
- **Coding:** <…>
- **Infrastructure:** <…>

## Assumptions carried into the delivery
- <unverified fact the work rests on — whether the run ended up confirming it — what to check if it's wrong. `none — every load-bearing fact was verified` is a valid answer, and a claim.>

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

- **Every acceptance criterion captured at Intake appears in the Requirement coverage
  table** — including the ones that ended uncovered or out of scope. A criterion
  missing from the table is how a dropped requirement ships unnoticed; a table
  where every row is ✅ but one criterion never appears is worse than an honest ❌.
- **Evidence is a test name or a review finding**, not "task done". A completed
  task is a worker's claim; evidence is what makes it checkable.
- Status is **not** ✅ Done if any criterion is ❌ not covered, regardless of the
  review verdict or the per-stage gates.
- **Trade-offs are consolidated, never invented** — only what stages actually
  surfaced. An empty section says `none surfaced`.
- **Report honestly.** Shrunk scope, a degraded quality bar, or an accepted risk
  goes here in plain language — first, not buried under Follow-ups.
- **A cost warning from `cost-budget` (≥80% of an envelope) is reported even on a
  ✅ Done** run.
- Status is ✅ Done only when every Definition-of-Done item in the agent
  definition is true. If any is false, say so plainly.

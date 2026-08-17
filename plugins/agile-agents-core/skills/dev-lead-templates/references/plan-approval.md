# Plan-approval prompt (dev-lead Stage 4)

The **only mandatory *approval* gate** — "only" counts approvals, not questions;
intake may already have asked about an ambiguity, an undiscoverable profile field,
or the criteria derived from a plan file. Rendered via `ask_user` *after* the child
tasks exist in the tracker, so the human reviews concrete, linked work items — not
an abstract outline.

When the run was seeded with a **plan file**, this gate changes meaning but not shape:
it is no longer "here is the plan I wrote" but "here is your plan, reconciled into
tracker tasks — confirm I did not lose or distort a step". The *Changes I made to your
plan* line is the substance of that confirmation, so fill it honestly and never
collapse a split, a merge, a re-order or a drop into silence.

The *Assumptions this plan rests on* line is the other one not to soften. It is the
only point where a human sees what the plan took on trust before autonomous execution
starts, and the cheapest place to correct it — a reader who knows the quota, the tier or
the API answers it in one line, where the run would otherwise spend a stage discovering it.
List an assumption even when you think it is safe; `none` is a claim that Stage 1 verified
everything load-bearing, not a default.

*Acceptance criteria I derived* works the same way for a different failure. A requirement
that states no criteria does not stall Intake — the lead drafts them and confirms them
**here**, which is why they must be listed separately from the stated ones rather than
blended in. A derived criterion the human never saw would make the Stage 9 check measure
the lead's own reading of the requirement instead of the requirement, and that loop closes
silently: every gate passes and the delivered thing is still not what was asked for.

**Choices:** `Approve and run autonomously` / `Adjust plan` / `Cancel`.

```markdown
## Proposed plan for: <requirement title>

**Definition of Done:** <one sentence from Intake>
**Source:** <requirement / tracker item id / plan file path — when a plan file, say so: the tasks below are its steps, reconciled>
**Parent story:** <id / link>
**In scope:** <bulleted>
**Out of scope:** <bulleted>

**Tasks created (provisional — tagged `pending-approval`):**
1. <task-id> — <title> (<N> ACs)
2. ...
(overall approach recorded as a comment on the parent work item)

**Architect tasks not carried into the plan:** <task — reason, one line each, or `none` / `n/a (lightweight research)`>

**Changes I made to your plan:** <step — split / merged / re-ordered / dropped + one-line reason, each, or `none — every step carried as-is` / `n/a (no plan file supplied)`>

**Acceptance criteria not covered by any task:** <criterion — reason it is out of scope, one line each, or `none — every criterion maps to a task`>

**Acceptance criteria I derived — confirm or correct:** <numbered list of criteria the requirement did not state and you inferred from the outcome it describes, one line each, or `none — every criterion was stated verbatim`>

**Assumptions this plan rests on:** <unverified fact — what breaks if it's wrong — which task would surface it, one line each, or `none — every load-bearing fact was verified`>

**Stages I will run per task (autonomously after your approval):**
- Coding — <skip / run + 1-line reason>
- Testing — <skip / run + 1-line reason>
- Review — always run

**Stop conditions during autonomous run:** ambiguity, gate failure after one retry,
scope change required, destructive action, missing secret, tracker-write failure,
review verdict ❌ Block.

**Approve the plan to start autonomous run?**
```

## Handling the answer

- **Approve** → have `backlog-manager` remove the `pending-approval` tag from the
  created tasks, then proceed to Stage 6 and run autonomously through Done.
- **Adjust** → take the human's edits, have `backlog-manager` revise the affected
  tasks (add / remove / re-scope), re-render this template, ask again. No silent
  re-planning.
- **Cancel** → this authorises cleanup of the provisional tasks: have
  `backlog-manager` close / remove the `pending-approval` child items created in
  this run, mark all SQL todos `blocked` with reason "user cancelled at plan gate",
  and stop. List any ids that could not be cleaned up automatically.

After approval, ask no further questions unless a stop condition fires.

# Plan-approval prompt (dev-lead Stage 4)

## Prompt

The **only mandatory *approval* gate** — "only" counts approvals, not questions;
intake may already have asked about an ambiguity, an undiscoverable profile field,
or the criteria derived from a plan file. Rendered via `ask_user` *after* the child
tasks exist in the tracker, so the human reviews concrete, linked work items — not
an abstract outline.

For a supplied plan, account for every split, merge, reorder and drop. Separate
derived acceptance criteria for human confirmation. Expose all unverified
assumptions, consequential choices and feasibility-dependent work. Relay Research
trade-offs, risks and decision gaps without dismissing them; add the lead's own
choices with alternatives and recommendations. Use `none` only after checking.

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

**Trade-offs in this approach:** <the choice — what was rejected — what it costs, one line each. Relay every trade-off Research surfaced (`architect`'s *Key tradeoffs*) plus any you made while decomposing. `none — no non-obvious choice was made` is a claim, not a default.>

**Decisions I made that you may want to change:** <the call — the alternative — why I chose this, one line each. These are the consequential judgement calls taken without asking, listed here rather than raised as separate questions. `none — nothing consequential was left unspecified`.>

**Risks and open questions:** <risk or question — impact if it goes the wrong way — who owns it, one line each. Relay `architect`'s *Open questions / risks* and *Decision gaps* verbatim in substance; add your own. `none` only after looking.>

**What dies if a feasibility task returns ❌:** <the dependent tasks, per feasibility task, or `n/a — no feasibility task in this plan`>

**Stages I will run per task (autonomously after your approval):**
- Coding — <skip / run + 1-line reason>
- Testing — <skip / run + 1-line reason>
- Review — always run

**Stop conditions during autonomous run:** ambiguity, gate failure after its retry budget,
scope change required, destructive action, missing secret, tracker-write failure,
review verdict ❌ Block.

**Approve the plan to start autonomous run?**
```

### Return the answer

Return the selected choice and feedback unchanged to `dev-lead`. The supervisor's
Stage 4 owns approval, task revision, cancellation cleanup and the subsequent
conditional design gate. This rendering template authorises no transition.

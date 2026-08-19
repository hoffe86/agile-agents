# ADR 0003 — Test-bar gate placement between Stage 4 (Test) and Stage 5 (Review); max 3 retries → halt

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H3)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H3); Stream A §13.3; Stream E §17, §22
- **Note (2026-08):** stage numbers below are the ones in force when this ADR was accepted. The pipeline has since been renumbered sequentially (the fractional 1.5/1.6/1.7/2.5/4.5 are gone), and ADR 0009 later merged the Coding and Testing stages into a single Implement stage, shifting everything after it down by one. The decision is unchanged — the gate still sits between implementation and review. Original → today: 1.5→2, 1.6→3, 1.7→4, 2.5→5, 3+4→6 (Implement, code + tests), 4.5→7 (this gate), 5→8 (Review), 6→9 (Done).
- **Amendment (2026-08-19) — retry budget is now three.** See the *Amendment* section below. The placement decision is unchanged.

## Context

Reviewer agents (architecture-review, code-review, infra-review,
testing-review, security-review) are the most expensive stage of the
pipeline — they are tier-`heavy` (see ADR 0007), they run in parallel, and
they read large amounts of context. Spending five reviewer dispatches on a
patch that doesn't even compile is pure waste.

Cognition's autofix loop (Stream E §17) and Stripe's deterministic graders
(§22) both place a deterministic, automated quality bar *before* the
expensive judgement steps. We want the same shape.

Three placement options exist within our stage table
(`plugins/agile-agents-core/agents/dev-lead.agent.md` Stage 0–6):

- **Before Stage 4 (Test):** between Coding and Testing.
- **Between Stage 4 (Test) and Stage 5 (Review):** after the testing agent
  has authored / updated tests.
- **After Stage 5 (Review):** as a last sanity check before merge.

## Decision

The `test-bar-gate` skill runs **between Stage 4 and Stage 5**, immediately
after the testing agent emits `TESTS COMPLETE`. The gate executes
**lint → typecheck → unit-test**, fail-fast on the first non-zero exit, with
per-stack commands resolved from `solution-profile.yaml: tech_stack` (or the
`quality_gates.test_bar.*` overrides).

**Retry policy:** at most **3 retries** delegated back to the appropriate
author (`coding` for application code and its tests, `infrastructure` for IaC)
with the gate failure as context. On the **4th failure** the dev-lead emits
`run.abort` with reason `test_bar_unrecoverable`, does not call any reviewer,
and uses `ask_user` to hand the persistent failure to a human. The loop is also
abandoned early if a retry closes nothing — see the Amendment below.

### Why between Stage 4 and Stage 5

- After Stage 4 (not before): the testing agent may legitimately add or
  modify tests, which can change which tests run and whether they pass.
  Gating before Stage 4 would gate the wrong revision of the codebase.
- Before Stage 5 (not after): the entire economic point is to spare
  reviewer cost on broken patches.

### Why a bounded retry budget

*(Originally "Why max 2 retries" — see the Amendment above; the budget is now 3, and the
reasoning below is why it is bounded at all and why it stops where it does.)*

- 0 retries → flaky environments (transient network test failure,
  package-cache miss) would falsely abort runs.
- ≥ 3 retries → the loop becomes the failure mode. Industry observations
  (Magentic-One, Cursor scaling experiments — research §19) consistently
  show that beyond 2–3 retries within a phase, replanning at the outer loop
  outperforms further in-phase retries. Halting and asking the human is the
  cheaper outer-loop replan.

**Where the amended budget sits against that evidence — stated plainly, because it is the
weakest point of the amendment.** Three is the *top* of the 2–3 band the cited research
supports, not comfortably inside it. The amendment is defensible for this gate specifically
because the failures here are deterministic (a compiler or test-runner error, not a
judgement), which is the case where in-phase retrying converges best. It would **not** be
defensible to read this as general licence for longer loops elsewhere.

The convergence rule is what keeps three safe rather than merely permitted: a round that
closes nothing ends the loop immediately, so the budget is a ceiling on *productive* rounds,
not a quota to spend. Without that rule, three retries would sit on the wrong side of the
evidence above.

## Consequences

**Positive**
- Reviewer dispatches are never spent on a non-building patch.
- Deterministic, replayable signal: lint + typecheck + unit-test results
  appear in the JSONL run log (ADR 0006) as `gate_check` events.
- Per-project tunability via `solution-profile.yaml` without forking the
  skill.

**Negative**
- Two retries can still cost real money on a slow test suite — partially
  mitigated by `cost_envelope` (ADR 0004) which checkpoints after every
  stage.
- Stacks without an auto-detected command palette emit
  `outcome=skipped` and pass through with a warning — the gate is
  best-effort, not absolute.

## Amendment (2026-08-19) — retry budget raised from 1/2 to 3

**What changed.** The gate now allows **three** corrective retries (abort on the 4th), and
the Stage 8 review/fix loop allows **three** corrective rounds rather than one.

**Why it needed an amendment at all.** A review of all 15 ADRs found this one had drifted
from its implementation: it decided 2 retries, while `test-bar-gate/SKILL.md` allowed 1 and
`dev-lead` claimed 2 — three different numbers across the ADR, the skill and the agent. ADR
0009 superseded only this ADR's *stage numbering* and explicitly left the gate decision
standing, so the retry count had changed with no decision recorded anywhere. The numbers are
now reconciled at three in all three places.

**Why three is defensible here.** This gate is fully deterministic — a linter, a type
checker, a test runner. Each retry hands the author a concrete error rather than a judgement
call, so rounds genuinely converge, and the one-retry budget was throwing away runs that a
second or third pass would have cleared. That reasoning is specific to deterministic gates:
it does **not** license longer loops on LLM-judged steps generally.

**The countervailing risk, and the guard.** More retries means more spend on a run that may
be going nowhere, and `cost-budget` (ADR 0004) already flags author/reviewer ping-pong as the
canonical envelope-burner. So the budget is paired with a **convergence rule**: if a round
closes nothing — same findings still open, or more than before — the loop is abandoned
immediately rather than spending the remaining rounds. `review-lead` reports
`Round movement: closed / still open / newly raised` so `dev-lead` can apply that
mechanically instead of inferring it. Three is a ceiling, not a quota.

**Unchanged:** the gate's placement between implementation and review, its fail-fast ordering
(lint → typecheck → unit-test), `run.abort` with `test_bar_unrecoverable` as the terminal
state, and the deploy-verify carve-out where quota / policy denial / missing role assignment
halts immediately with **no** retry — no agent can resolve those, and retrying burns the
envelope on a deterministic failure.

**Deliberately not changed:** the design-approval **Adjust** cap (one round per run, in
`dev-lead-templates/references/design-approval.md`). That is a *human* decision loop at an
approval gate, not an automated corrective loop — the human is present and can simply decide
again, so a retry budget does not apply.

## Alternatives considered

- **Place before Stage 4.** Rejected: the testing agent legitimately changes
  what tests exist; gating on the pre-test snapshot is the wrong question.
- **Place after Stage 5.** Rejected: defeats the purpose — reviewer cost has
  already been spent.
- **Unbounded retries.** Rejected: a stuck loop on a flaky test is worse
  than asking the human; the cost envelope would catch it eventually but at
  much higher waste.
- **0 retries (one-shot gate).** Rejected: too many false aborts on
  transient environment issues.

## References

- `plugins/agile-agents-core/agents/dev-lead.agent.md` (Stage 4→5 boundary;
  retry table; halt-on-3rd-fail policy)
- `solution-profile.yaml` → `quality_gates.test_bar:` block
  (`quality_gates.test_bar` block)
- `skills/test-bar-gate/` (skill implementation,
  per-stack `references/commands.yaml` palette)
- `docs/research/autonomous-coding-agents-2026.md` §13.3, §17 (Cognition),
  §22 (Stripe), §19 (Magentic-One stall handling)

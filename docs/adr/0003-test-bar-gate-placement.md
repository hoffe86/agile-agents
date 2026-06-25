# ADR 0003 — Test-bar gate placement between Stage 4 (Test) and Stage 5 (Review); max 2 retries → halt

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H3)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H3); Stream A §13.3; Stream E §17, §22

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
(`agents/dev-lead.agent.md` Stage 0–6):

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

**Retry policy:** at most **2 retries** delegated back to the appropriate
author (coding or testing) with the gate failure as context. On the **3rd
failure** the dev-lead emits `run.abort` with reason
`test_bar_unrecoverable`, does not call any reviewer, and uses `ask_user` to
hand the persistent failure to a human.

### Why between Stage 4 and Stage 5

- After Stage 4 (not before): the testing agent may legitimately add or
  modify tests, which can change which tests run and whether they pass.
  Gating before Stage 4 would gate the wrong revision of the codebase.
- Before Stage 5 (not after): the entire economic point is to spare
  reviewer cost on broken patches.

### Why max 2 retries

- 0 retries → flaky environments (transient network test failure,
  package-cache miss) would falsely abort runs.
- ≥ 3 retries → the loop becomes the failure mode. Industry observations
  (Magentic-One, Cursor scaling experiments — research §19) consistently
  show that beyond 2–3 retries within a phase, replanning at the outer loop
  outperforms further in-phase retries. Halting and asking the human is the
  cheaper outer-loop replan.

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

- `agents/dev-lead.agent.md` (Stage 4→5 boundary;
  retry table; halt-on-3rd-fail policy)
- `solution-profile.yaml` lines 159–193
  (`quality_gates.test_bar` block)
- `skills/test-bar-gate/` (skill implementation,
  per-stack `references/commands.yaml` palette)
- `docs/research/autonomous-coding-agents-2026.md` §13.3, §17 (Cognition),
  §22 (Stripe), §19 (Magentic-One stall handling)

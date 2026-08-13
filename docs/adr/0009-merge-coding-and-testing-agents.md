# ADR 0009 — Merge the `coding` and `testing` agents into one author, with the craft split across two skills

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (agent-roster consolidation)
- **Supersedes in part:** ADR 0003 (stage numbering only — the gate placement decision stands), ADR 0006 (the `agent` enum), ADR 0007 (the `mid` tier roster)

## Context

The suite shipped `coding` and `testing` as separate author agents: `coding`
wrote production code and was explicitly forbidden from touching test files;
`testing` wrote and ran the tests and was explicitly forbidden from touching
production code. `dev-lead` ran them as consecutive stages (6 and 7), each with
its own gate and its own sentinel block (`IMPLEMENTATION COMPLETE`,
`TESTS COMPLETE`).

The split was inherited from the shape of the pipeline, not from evidence that
it worked. In practice it bought less than it cost:

- **It is not how the work is actually done.** A developer who writes a
  behaviour writes the test for it; the two activities interleave —
  red-green-refactor is a loop, not a hand-off. Forcing a stage boundary
  between them means the agent with the most context about *why* the code is
  shaped this way is not the one asserting what it should do.
- **It bought a hand-off round, not independence.** Every task paid a full
  context transfer (the `IMPLEMENTATION COMPLETE` block, re-read of the diff,
  re-derivation of intent) so that a second agent could write assertions
  against code it had to reverse-engineer. The genuine independent judgement in
  this pipeline is the reviewers' — `test-review` in particular — and those are
  different agents either way.
- **Split ownership produced ping-pong.** `testing` could not fix production
  code, `coding` could not fix a test, so a red test that revealed a real defect
  had to bounce back through `dev-lead`. The retry tables in `test-bar-gate`
  existed largely to adjudicate *which of the two* owned a failure — a routing
  problem the split itself created.
- **The stage separation was already leaking.** `infrastructure` owned its own
  IaC tests end-to-end, so Stage 7 carried an "IaC-only skip" whose sole job was
  to avoid delegating to an agent that had nothing to do. Two of the three
  author agents already tested their own work.

The counter-argument is real and is the reason the split existed: **an author
who owns the tests can make a failure disappear by weakening the assertion.**
That risk is what any consolidation has to answer for.

## Decision

**One author agent, `coding`, owns application code and the tests that cover
it.** The `testing` agent is removed. `infrastructure` is unchanged — it already
owned its IaC tests.

Concretely:

1. **One sentinel block.** `IMPLEMENTATION COMPLETE` absorbs the test fields
   (`Test files changed`, `Test run`, `Coverage on touched files`,
   `Existing tests modified`). `TESTS COMPLETE` is **retired** — a second block
   from the same agent would give `dev-lead` two gates over one diff.
2. **One stage.** Stages 6 (Coding) and 7 (Testing) merge into **Stage 6 —
   Implement (code + tests)**, gated once per task. Everything after shifts down
   one: 7 = Automated gates, 8 = Review, 9 = Done. The IaC-only skip disappears
   with the stage it guarded.
3. **The craft moves into two skills**, both loaded by the one agent:
   `development-practices` (implementation bar) and `testing-practices`
   (verification bar). Keeping them as separate skills means the two concerns
   stay separately editable and separately loadable — a coverage-only task loads
   just `testing-practices` — while the agent file shrinks to role, routing and
   tool grant.
4. **The asymmetry rule replaces the split.** The author *may* change production
   code to make a test pass — that is now the point — but **may never weaken a
   test to make production code pass.** Every modified existing test is
   justified in the `Existing tests modified` field, naming what the old
   assertion claimed and why that claim was invalid.
5. **Three independent checks enforce rule 4**, because a rule the author
   applies to itself is not a control:
   - `dev-lead`'s per-task gate **fails outright** on an unexplained assertion
     change, a deleted test, or a newly-skipped test.
   - `test-bar-gate` is a **script**, not an opinion, and runs over the combined
     diff — it cannot be talked into passing.
   - `test-review` receives the `Existing tests modified` lines with the diff
     and raises 🔴 Critical on any weakening that does not hold up. It is now
     the *only* second pair of eyes on the tests, which is stated explicitly in
     its agent definition.

## Consequences

**Positive**
- One hand-off round removed per task, and with it a context transfer that
  existed only to re-establish what the previous agent already knew.
- A red test that exposes a real defect is fixed where it is found, instead of
  bouncing between two agents via the orchestrator.
- Failure routing is simplified: `coding` owns application failures, whatever
  layer the file is in; `infrastructure` owns IaC failures. The
  `test-bar-gate` retry table stops adjudicating ownership and starts asking the
  question that matters — was the code wrong, or the assertion?
- The roster is smaller (12 agents), and the model-tier / event-schema /
  finding-owner enums lose an entry each.
- Test guidance is now a skill, so it is reusable by anything that writes tests
  rather than being locked inside one agent definition.

**Negative**
- **The author marks its own homework.** The mitigations above are gates, not
  proofs; a determined weakening with a plausible justification can still get
  through to `test-review`. This is a real transfer of risk from "structurally
  impossible" to "detected downstream", accepted because the structural version
  was costing a round on every task and because `test-review` was always the
  agent whose judgement actually counted.
- `test-review` becomes load-bearing. If a project's review budget skips it, the
  independent check on tests is gone entirely. It remains auto-invoked whenever
  the diff touches tests or adds testable code.
- One agent now carries two skill bodies, so its context is larger per task than
  either predecessor's was. Splitting the guidance into two separately loadable
  skills bounds this: a coverage-only task need not load the implementation bar.
- Stage renumbering invalidates stage references in anything written against the
  old table (see ADR 0003's note).

## Alternatives considered

- **Keep both agents, reduce the hand-off.** Rejected: the cost is the stage
  boundary itself, not the verbosity of the block. Shrinking the block keeps
  every problem and removes the audit trail.
- **Merge, and keep both sentinel blocks.** Rejected: two blocks from one agent
  means two gates over one diff and a `dev-lead` that must decide what a
  `TESTS COMPLETE` adds when it already parsed the tests in
  `IMPLEMENTATION COMPLETE`.
- **Merge and inline all guidance into the agent file.** Rejected: the file
  would carry both craft bodies with no way to load one without the other, and
  the testing bar would stay locked inside a single agent.
- **Two skills, but split as `development` / `testing` *agents* sharing them.**
  Rejected: that is the status quo with extra indirection — the hand-off round
  is the cost, and sharing skills does not remove it.
- **Rename the merged agent** (`development`, `engineering`, `developer`).
  Rejected: `coding` is referenced by `dev-lead`'s `agents:` list, the event-log
  agent enum, eval fixtures and ~60 doc references; the rename buys accuracy in
  the name at the cost of a much wider blast radius, and the description carries
  the scope.

## References

- `plugins/agile-agents-core/agents/coding.agent.md` (merged agent; hand-off contract)
- `plugins/agile-agents-core/skills/development-practices/SKILL.md`
- `plugins/agile-agents-core/skills/testing-practices/SKILL.md` (§2 — the asymmetry rule)
- `plugins/agile-agents-core/agents/dev-lead.agent.md` (Stage 6 gate; renumbered stage table)
- `plugins/agile-agents-core/agents/test-review.agent.md` (independent judgement on author-written tests)
- `plugins/agile-agents-core/skills/test-bar-gate/SKILL.md` (retry routing)
- ADR 0003 (gate placement — unchanged), ADR 0006 (event schema `agent` enum), ADR 0007 (`model_tier` roster)

# ADR 0008 — Layered evaluation strategy (trajectory / review-detection / outcome)

- **Status:** Accepted
- **Date:** 2026-06
- **Deciders:** eval harness hardening (follow-on to ADR 0002 self-benchmarking composition)
- **Related:** ADR 0002 (self-benchmarking harness), ADR 0003 (test-bar gate), ADR 0004 (cost envelope), ADR 0006 (run-event-log schema)

## Context

The harness started with a **single** evaluation type: an end-to-end outcome eval
(`eval/`) that runs `dev-lead` on a task and scores the produced artifact against
`acceptance.md`. That eval is necessary but, on its own, a blunt instrument:

- **It conflates four phases.** The RPI pipeline is Research → Plan → Implement →
  Review. A single `resolved` / `failed` verdict can't say *which* phase failed —
  research misread the repo, plan decomposed badly, implement built the wrong thing,
  or review waved a defect through all collapse to the same score.
- **It's slow and credit-heavy.** A real run executes the full multi-agent pipeline
  and calls the model many times; the LLM judge adds another call. This makes it
  unsuitable as a per-PR gate.
- **It is blind to process failures.** A run can produce a plausible artifact while
  its own machinery never fires. Observed in a real `task-03` run: a correct Bicep
  module was produced, but **zero** `run-event-log`, `test-bar-gate`, and
  `cost-budget` events were emitted. The outcome eval scored the artifact and never
  noticed the pipeline had effectively run as a single undifferentiated agent.

The RPI chain emits distinct, inspectable artifacts at each step (event-log stream,
task decomposition, code, review findings). That means the pipeline can be *observed*
per phase, not just judged at the end — if we add the right eval types.

## Decision

Adopt a **layered evaluation pyramid**, mirroring the test pyramid: many cheap
deterministic checks at the base, few expensive end-to-end checks at the top. Each
layer targets a different phase and failure mode.

| Layer | Name | Targets | Cost | Gate? |
| --- | --- | --- | --- | --- |
| **L0** | Trajectory / process conformance | the whole RPI chain *as a process* | zero-credit, deterministic | yes — every push/PR |
| **L1** | Review-detection (planned) | the Review phase | medium (review agents only) | on demand |
| **L2** | Outcome (existing, `eval/`) | the Implement phase end-to-end | high (full pipeline + judge) | no — manual checkpoint |

**L0 is built now** (`eval/pipeline/trajectory/`): assertions over the `run-event-log` JSONL
stream (ADR 0006) verifying dev-lead bookends, RPI phase ordering, a test-bar
`gate_check` (ADR 0003) before review, reviewer `gate_check`s, and cost telemetry
(ADR 0004). It runs against a golden fixture generated from one in-code source, plus
a self-test that proves each assertion trips. No model is called, so it is safe to
gate on.

**L1 is specified but deferred** (see *Not doing yet*).

**L2 is the existing outcome eval**, reframed as the top of the pyramid: the
integration checkpoint, run manually or on demand, never a per-PR gate.

## Consequences

**Positive**
- A failing run is now *diagnosable*: L0 says "the pipeline didn't run its gates",
  L2 says "the output was wrong" — different problems, different fixes.
- The base of the pyramid is free and deterministic, so process regressions
  (an agent that stops emitting events, a skipped test-bar gate) are caught on every
  push — exactly the failure that was previously invisible.
- The expensive L2 eval is no longer asked to do a job it's bad at (catching process
  drift), so its credit budget is spent only on what it's uniquely good at.

**Negative**
- More moving parts: three eval types instead of one, two CI workflows
  (`trajectory-eval.yml` free/gating, `eval.yml` credit-heavy/manual).
- L0 asserts the *shape* of a run, not its correctness — a pipeline could emit a
  perfectly-shaped event stream while doing poor work. L0 is a necessary, not
  sufficient, signal; it complements L2, it doesn't replace it.
- The golden fixture must be kept in sync with the event-log schema (mitigated by
  generating it from `build_golden()` and diffing in CI).

## Not doing yet

- **L1 review-detection.** Seed a fixed diff with known issues across categories
  (1 security, 1 architecture, 1 test-gap, 1 infra), run only the review agents, and
  measure recall (caught/total) + precision (real/flagged). Highest-ROI next layer —
  review is the suite's main value proposition and its quality is otherwise invisible,
  and it's far cheaper than L2 because it skips Research/Plan/Implement. Deferred only
  to keep this change small; no blocker.
- **Plan-quality eval.** Needs reference decompositions, stays subjective, rots fast.
  Defer indefinitely.
- **Research-recall eval.** Valuable but needs hand-labelled gold file-sets per task.
  Defer until the localisation backend is swapped (research spike H1) and there is
  something to measure against.
- **Judge calibration.** The L2 LLM judge will eventually need a calibration check
  against a few human-labelled runs. YAGNI until labelled runs exist.

## Alternatives considered

- **Keep a single end-to-end eval.** Rejected: blind to process failures (the
  motivating `task-03` bug), slow, and undiagnosable per phase.
- **Build all eval types at once (research, plan, implement, review, trajectory).**
  Rejected: most need labelled reference data that doesn't exist yet; plan/research
  evals would rot. Build the two cheap/high-signal layers first (L0 now, L1 next).
- **Per-agent unit eval for every agent.** Rejected: only the review agent's quality
  is both high-value and otherwise-invisible enough to justify a dedicated layer;
  the rest are covered transitively by L0 (process) + L2 (outcome).

## References

- `eval/pipeline/trajectory/check-trajectory.py`, `eval/pipeline/trajectory/README.md`
- `.github/workflows/trajectory-eval.yml` (L0, gating) and `.github/workflows/eval.yml` (L2, manual)
- ADR 0002 (self-benchmarking composition), ADR 0003 (test-bar gate), ADR 0004 (cost envelope), ADR 0006 (run-event-log schema)
- `skills/run-event-log/references/event-schema.json`

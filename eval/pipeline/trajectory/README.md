# `eval/pipeline/trajectory/` — L0 trajectory eval (process conformance)

The cheapest layer of the eval pyramid (see [ADR 0008](../../docs/adr/0008-layered-evaluation-strategy.md)).
It grades **how the pipeline ran**, not what it produced: given a
[`run-event-log`](../../skills/run-event-log/SKILL.md) JSONL stream, it asserts the run
conformed to the expected RPI shape. **Deterministic, zero-credit, no model calls** — so it can
run on every push/PR and even gate.

## Why this layer exists

The end-to-end outcome eval (`../README.md`) answers *"was the output good?"* — but it's slow,
credit-heavy, and a single `failed` tells you nothing about *which* phase broke. Worse, a run can
produce a plausible artifact while its own machinery never fired. In a real `task-03` run the
agent wrote a correct Bicep module but emitted **zero** `run-event-log`, `test-bar-gate`, and
`cost-budget` events — invisible to an outcome score. This checker catches exactly that class of
silent process failure, for free.

## What it checks

`check-trajectory.py` runs 14 assertions over the event stream:

| Group | Checks |
|---|---|
| Structural | required fields present; valid `agent` / `event_type` enums; single `run_id`; first event is `dev-lead run_start`; last is `dev-lead run_complete` with an outcome; `phase_start`/`phase_complete` balanced |
| RPI trajectory | a research phase ran; an implement phase ran; a **test-bar `gate_check` (dev-lead) fired after implement and before review**; ≥1 reviewer emitted a `gate_check`; review came after implement |
| Telemetry | every `phase_start` has a matching `phase_complete`, so measured usage can be attributed to a phase; and no event carries a self-reported `cost_usd` / token field, because no agent can observe its own spend |

All are required: the checker exits `0` only when every check passes, `1` otherwise.

## Usage

```bash
# Grade a real run's event log
python eval/pipeline/trajectory/check-trajectory.py .copilot-runs/<run-id>/events.jsonl

# Verify the checks themselves (mutates an in-code golden; no file, no model)
python eval/pipeline/trajectory/check-trajectory.py --self-test

# Regenerate the golden fixture after changing build_golden()
python eval/pipeline/trajectory/check-trajectory.py --emit-fixture eval/pipeline/trajectory/fixtures/full-run.events.jsonl
```

## Fixture

`fixtures/full-run.events.jsonl` is a recorded "good" run — a 26-event successful RPI trajectory.
It is the deterministic anchor the CI checks against. It is **generated from `build_golden()`**
inside the checker (single source of truth), so the [`Eval · pipeline trajectory`](../../../.github/workflows/eval-pipeline-trajectory.yml)
workflow regenerates it and fails if the committed copy drifted. Edit `build_golden()`, then
re-emit and commit — never hand-edit the fixture.

## Wiring a real run into this

`dev-lead` writes events to `${COPILOT_RUNS_DIR:-.copilot-runs}/<run-id>/events.jsonl` via the
`run-event-log` skill. Point the checker at that file after a run. (The skill scripts currently
need to be reachable from the run's working directory for the agent to emit — see the open
follow-up in the main `eval/README.md` about event scripts not firing in a fresh workspace.)

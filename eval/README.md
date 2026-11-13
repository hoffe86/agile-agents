# Evaluation

Evaluation has three separate responsibilities. Their results are not interchangeable.

| Responsibility | Tool / location | What the evidence means |
|---|---|---|
| Pipeline scoring | DeepEval, [`deepeval/`](deepeval/README.md) | Coverage of expected skill identities in existing Copilot JSONL traces |
| Deterministic process checks (L0) | [`pipeline/trajectory/`](pipeline/trajectory/README.md) | Conformance of a harness event log to its RPI ordering, gates and telemetry contracts |
| Skill evaluation | Waza, [`skills/`](skills/README.md) | Offline hygiene and a manual current-core outcome check; historical efficacy experiment |

DeepEval is the sole active pipeline-scoring path
([ADR 0015](../docs/adr/0015-deepeval-for-pipeline-evaluation.md)).
Waza remains the skill evaluator
([ADR 0014](../docs/adr/0014-skill-evaluation-with-waza.md)); deterministic L0
checks remain independent
([ADR 0008](../docs/adr/0008-layered-evaluation-strategy.md)).

ADR 0015 is historical: current direction retires grading whether Copilot
invoked expected skills. The manual invocation-grading workflow has been
removed. Local scoring remains available, and synthetic checks exercise
evaluation infrastructure rather than Copilot's loading behaviour. Waza
evaluates skill quality.

## Pipeline scoring and boundaries

The scorer reads existing logs and measures recorded skill invocation using the
pinned DeepEval 4.1.8 `ToolCorrectnessMetric`. It does not launch agents, call
models, execute recorded commands or run generated artifacts. Expected skill
identities are supplied by the operator. Matching every identity scores 1.0;
missing identities give fractional coverage or 0. Invalid inputs and environment
errors are reported separately from measured failures.

Recorded invocation is **not** successful tool completion, correct skill use,
task acceptance or an authenticated benchmark of the current harness. The
synthetic demonstration fixture proves the scoring wiring, not harness quality.
Live end-to-end runs exist only for the custom-eval tasks (next section); they are
**not OS-sandboxed**, and sandbox/controller work is deferred to
[#22](https://github.com/hoffe86/agile-agents/issues/22).
Legacy/live options of this offline scorer are not aliases for anything else.

The cold-start scorer regression permits only trusted CPython Windows version
probing and urllib3's loopback IPv6 capability bind. It rejects external
connections, DNS, other process/bind attempts and recorded-command execution.
This is evidence for the exercised offline path, not an OS sandbox or a claim
of zero subprocesses/socket operations. See the
[operational reference](deepeval/README.md#offline-boundary).

## Code and data ownership

First-party Python lives in [`python/agile_eval/`](python/agile_eval/), imported
through the single `eval/python` source root. It does not shadow third-party
`deepeval`. The trace adapter owns parsing and schema validation; the report
module owns discovery, scoring and sanitized summaries; the offline model helper
supplies telemetry/configuration safeguards and a fail-on-call model stub.
`deepeval/` owns the operational entrypoint, locked dependencies and scorer tests.

[`pipeline/custom-eval/`](pipeline/custom-eval/README.md) holds ten tasks for live
evaluation: `agile_eval.custom_eval` stages a task, drives dev-lead through the Copilot CLI,
and scores the run with DeepEval — plan gate, delegation, and forbidden reviewer
workflows against each task's
`expectations.yaml` — plus command checks for build, test and render criteria and an
optional model judge over the captured diff for the rest. A missing tool leaves its
criterion `UNVERIFIED`, never failed. Simulated LLM plan approval is implemented but
the current CLI transport cannot verify the approval request, so it blocks rather than
resuming. The real harness's human gate is unchanged.
[`pipeline/swe-bench-subset/`](pipeline/swe-bench-subset/README.md) retains a
25-instance manifest, not an installed dataset or an executable suite.
The [outcome rubric](pipeline/scoring-rubric.md) records how acceptance evidence is
interpreted; the custom-eval scorer implements it.

[`baselines.md`](baselines.md) contains historical measurements with their
original limitations. These are not recomputed or promoted to current scores.
`pipeline/runs/` remains the gitignored location for local summaries and existing
run artifacts. Existing user outputs are not inputs to a migration or cleanup.

### Retained run provenance

Historical rows and retained summaries without a trusted provenance binding remain
**legacy/unattributed**, not reproducibility evidence. Do not backfill them with
today's revision, input hashes or requested model identities. Historical sidecars
and hashes, where present, are unsigned integrity metadata—not independent proof
of the executing runtime or model. The retired provenance tooling is not an active
verification API. The current offline scorer measures supplied trace contents;
it does not authenticate historical runs or grant outcome credit. These limits
preserve the classifications and numbers in [`baselines.md`](baselines.md).

## Commands and CI

Installation, CLI arguments, result schema, exit codes and test commands are in
[`deepeval/README.md`](deepeval/README.md). The active scoring command is:

```bash
python eval/deepeval/report_skill_usage.py path/to/existing/logs --score --expect-skill architecture-decision-records --output eval/pipeline/runs/skill-usage-summary.json
```

### CI

The [skill workflow](../.github/workflows/eval-skills.yml) runs
dependency/runtime contract checks and the Waza skill checks. L0 retains its
own [trajectory workflow](../.github/workflows/eval-pipeline-trajectory.yml).
No scoring demonstration grants live-execution readiness or L2 outcome credit.

# Evaluation

Evaluation has three separate responsibilities. Their results are not interchangeable.

| Responsibility | Tool / location | What the evidence means |
|---|---|---|
| Pipeline scoring | DeepEval, [`deepeval/`](deepeval/README.md) | Coverage of expected skill identities in existing Copilot JSONL traces |
| Deterministic process checks (L0) | [`pipeline/trajectory/`](pipeline/trajectory/README.md) | Conformance of a harness event log to its RPI ordering, gates and telemetry contracts |
| Skill evaluation | Waza, [`skills/`](skills/README.md) | Routing, invocation and efficacy checks for individual skills |

DeepEval is the sole active pipeline-scoring path
([ADR 0015](../docs/adr/0015-deepeval-for-pipeline-evaluation.md)).
Waza remains the skill evaluator
([ADR 0014](../docs/adr/0014-skill-evaluation-with-waza.md)); deterministic L0
checks remain independent
([ADR 0008](../docs/adr/0008-layered-evaluation-strategy.md)).

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
Workspace-outcome scoring and live execution are unavailable; sandbox/controller
work is deferred to [#22](https://github.com/hoffe86/agile-agents/issues/22).
There is no runner, fixture-staging command, judge compatibility layer or
readiness API. Legacy/live options are not aliases for offline scoring.

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

[`pipeline/custom-eval/`](pipeline/custom-eval/README.md) retains ten benchmark
task specifications, profiles, input declarations and baseline source files.
[`pipeline/swe-bench-subset/`](pipeline/swe-bench-subset/README.md) retains a
25-instance manifest, not an installed dataset or an executable suite.
Their source-consistency tests do not stage workspaces or execute fixture commands.
The [outcome rubric](pipeline/scoring-rubric.md) records how to interpret task
acceptance evidence; it is not an implemented scorer.

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

### CI (on demand)

The manual [DeepEval offline scoring workflow](../.github/workflows/eval-pipeline-outcome.yml)
scores checkout-local traces; its synthetic fixture is a demonstration only.
Use local scoring for gitignored developer logs rather than importing remote
artifacts. Expected identities and trace paths are data, never shell source.
Only sanitized JSON summaries belong in workflow artifacts, not raw transcripts,
workspaces or credentials.

Its complete dispatch input contract is:

| Input | Meaning | Default |
|---|---|---|
| `trace_path` | Existing checkout-relative JSONL file or log directory; paths and symlinks must stay inside the checkout | `eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl` (**synthetic**) |
| `expected_skills` | Nonempty JSON array of nonblank skill identities, applied to each input log | `["fixture-skill-a"]` |

The workflow provisions Python 3.12 using hash-verified wheels from the pinned
evaluation lock, installs without an index, checks dependency closure and requires
the real DeepEval offline metric. The scoring threshold is 1.0. Exit codes remain
0 for all expectations recorded, 1 for measured failure, and 2 for input,
schema or setup errors; errors never become inferred scores.

The owned output is `eval/pipeline/runs/skill-usage-summary.json`. Existing output
files and redirected output paths are rejected. Only a summary created by the
scoring step is eligible for upload, including measured failures and schema/setup
error reports; input validation failures do not publish stale files. Artifact
retention is seven days. The job summary renders only status, measured/total counts
and threshold, not trace content or operator-supplied skill labels.

The independent [skill workflow](../.github/workflows/eval-skills.yml) runs
dependency/runtime contract checks and the Waza skill checks. L0 retains its
own [trajectory workflow](../.github/workflows/eval-pipeline-trajectory.yml).
No scoring demonstration grants live-execution readiness or L2 outcome credit.

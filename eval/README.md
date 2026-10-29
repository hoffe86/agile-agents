# `eval/` — Self-benchmarking harness for the dev-lead agent suite

## Purpose

This folder is the **measurement frame** for the coding-agent framework. It exists so we (and any
adopter who forks this template) can answer two questions with numbers, not vibes:

1. *Is the suite getting better or worse over time?* — track resolved/partial/failed rates across
   commits in `baselines.md`.
2. *Does change X actually help?* — re-run the harness before and after a change (e.g., adding the
   semantic localisation backend in H1, the test-bar gate in H3, etc.) and compare the deltas.

Self-benchmarking is the **first** improvement (Phase 1, item H2 in the improvement plan) for a
reason: every later quality lift needs a quantitative anchor to be measured against.

## How `eval/` is organised

One folder per **unit of evaluation** — the thing being graded — with shared Python
implementation in the `agile_eval` package:

```
eval/
├── README.md          this file
├── baselines.md       every tier's numbers, in one place
├── python/agile_eval/ shared Python implementation (metrics/ and adapters/ included)
├── deepeval/          dependency locks, tests and executable compatibility entrypoints
├── pipeline/          grades RUNS    — L0/L1/L2 (ADR 0008)
│   ├── trajectory/    L0 · process conformance over the event log (free, gating)
│   ├── custom-eval/   L2 · framework-representative tasks
│   ├── swe-bench-subset/  L2 · external comparable benchmark
│   └── run_eval.py, run-eval.{ps1,sh}, score-judge.{ps1,sh}, scoring-rubric.md, references/
└── skills/            grades SKILLS  — S0/S1/S2 (ADR 0014)
    ├── s0-routing/    should a prompt reach this skill (offline, free)
    ├── s1-invocation/ did the agent actually invoke it (model)
    └── s2-efficacy/   is the outcome better with it than without (2× model)
```

Import first-party modules as `agile_eval.authorization`, `agile_eval.grading`,
`agile_eval.provenance`, `agile_eval.run_eval`, etc., from the single trusted
`eval/python` source root. That root exposes only `agile_eval`, not a first-party
package named `deepeval`. No package installation or build backend is required.
Tests keep their existing discovery locations; `eval/conftest.py` supplies the
source root for pytest, and standalone unittest modules use the same root.
Historical executable paths remain tiny delegates, not library import facades.
The L0 trajectory and skill-eval layouts are unchanged.

The package keeps the grading dependencies one-way:

- `grading_contract`: pure verdict/result types, parsing, normalization, and uncertainty.
- `file_io`: bounded file/JSON I/O, path/reparse safeguards, and digest primitives.
- `workspace_inputs` → `file_io`: canonical fixture inventory, sibling-baseline
  verification, and safe workspace evidence enumeration.
- `provenance` → `file_io`, `workspace_inputs`, `grading_contract`: persisted
  manifests, bindings, terminal inventories, and retained-result validation/writing.
- `grading` → `grading_contract`, `workspace_inputs`, `provenance`: prompt composition,
  held preflight, and the grading CLI. Provenance never imports grading.

Consumers import functions from their owner rather than through compatibility
re-exports. Preparation and the run coordinator retain their existing responsibilities
and lazy dependency boundary. Sandbox/controller experimentation is tracked separately
in [#22](https://github.com/hoffe86/agile-agents/issues/22), not an active adapter.

**Why `pipeline/` and not `runs/`:** `eval/**/runs/` is the gitignored output directory
that `run-eval` writes into. Naming the source folder `runs/` would collide with its own
artifacts.

**An `agents/` folder is the obvious third slot** — grading `*.agent.md` rather than
skills or runs — and it is well-motivated: tool grants are a documented recurring defect
here (wrong in three separate PRs, silent in both directions), and Waza's
`tool_constraint` grader validates exactly which tools an agent used or avoided. It is
deliberately **not created empty**; add it when the first agent eval exists, and keep to
the convention above.

## Eval layers

This outcome eval is the **top** of a layered pyramid ([ADR 0008](../docs/adr/0008-layered-evaluation-strategy.md)):

| Layer | What it grades | Cost | Where |
|---|---|---|---|
| **L0** trajectory | *how* a run executed (RPI process conformance over the event log) | zero-credit, deterministic, gating | [`pipeline/trajectory/`](pipeline/trajectory/README.md) |
| **L1** review-detection | the Review phase (seeded-defect recall/precision) | medium | planned (ADR 0008) |
| **L2** outcome | *what* a run produced (acceptance vs. artifact) | credit-heavy, manual | [`pipeline/`](pipeline/) |

L0 runs free on every push/PR and catches process failures L2 is blind to; L2 (below) is the
end-to-end integration checkpoint.

### The S-layer — grading skills, not runs

L0/L1/L2 grade **runs**. A second axis grades the **artifacts** the runs load
([ADR 0014](../docs/adr/0014-skill-evaluation-with-waza.md)), using
[`microsoft/waza`](https://github.com/microsoft/waza) — whose unit of evaluation is
`SKILL.md` itself. It lives in **[`skills/`](skills/README.md)**, one directory per tier:

| Layer | What it grades | Cost | Where |
|---|---|---|---|
| **S0** skill hygiene | frontmatter validity, token budget, `copilot-instructions` drift | zero-credit, deterministic, **gating** | [`eval-skills.yml`](../.github/workflows/eval-skills.yml) |
| **S0** routing | should this prompt reach this skill (offline heuristic) | zero-credit | [`skills/s0-routing/`](skills/s0-routing/) — reports, uncalibrated |
| **S1** invocation | did the agent actually invoke it | model | [`skills/s1-invocation/`](skills/s1-invocation/README.md) |
| **S2** efficacy | is the outcome better than *not* loading it | 2× model | [`skills/s2-efficacy/`](skills/s2-efficacy/README.md) — blocked on isolation |

Run the free tier locally exactly as CI does:

```powershell
python scripts/check-skill-frontmatter.py --self-test   # prove each assertion trips
python scripts/check-skill-frontmatter.py               # 76 artifacts, strict YAML
python scripts/check-instructions-drift.py              # roster counts match reality
./scripts/check-skill-tokens.ps1                        # token ratchet + coverage
./scripts/run-trigger-evals.ps1                         # routing baseline
```

Two things S0 exists to stop, both of which had already happened:

- **A skill whose frontmatter does not parse is silently dropped by the CLI.** Not a
  theoretical risk — the installed core plugin had 36 skills on disk and offered 35, and
  the missing one was the only one whose YAML was invalid. It could never be invoked and
  nothing reported it.
- **Token budgets are a ratchet, not a target.** A skill body enters context when it
  triggers, so its size is recurring spend; the always-on set costs ~8,100 tokens on
  *every* agent turn. Limits in `.waza.yaml` sit at today's measured cost so a regression
  fails. Raising one to go green is metric gaming — trim the skill, or move detail into
  `references/`, which loads on demand rather than on trigger.

**A skill graded alone is not a skill in the pipeline.** Waza evaluates a skill in
isolation; ours run inside a 15-agent chain. The S-layer complements L0/L2 — it never
replaces them.

## Methodology

Two evaluation suites, both runnable through the same harness:

| Suite | Source | Size | Purpose |
|---|---|---|---|
| `swe-bench-subset/` | A 25-task stratified slice of [SWE-bench Verified](https://www.swebench.com/verified.html) | 25 tasks across 8 repos × 3 difficulty bands | External, comparable-to-literature benchmark |
| `custom-eval/` | Hand-written framework-representative tasks | 10 tasks covering C#, Python, Bicep, GHA, Helm, ADRs, threat modelling | Internal, breadth-of-framework benchmark |

For each task the harness:

1. Validates/stages custom-eval profiles and declared immutable original inputs.
2. Runs only in offline dry-run mode today; live execution fails closed because no verified OS sandbox is available.
3. When live execution is restored, the existing mandatory human plan-approval gate remains a separate requirement.
4. The intended scoring contract follows [`scoring-rubric.md`](pipeline/scoring-rubric.md):
   - **resolved** — all acceptance criteria pass
   - **partial** — some criteria pass, none failed catastrophically (no broken build)
   - **failed** — nothing meaningful produced or build broken
5. Writes `summary.json` and separate `run-provenance.json`; measured baselines are
   recorded manually in `baselines.md`.

## Retained run provenance

Both native runners capture **provenance schema 1** using `agile_eval.provenance`
in [`python/agile_eval/provenance.py`](python/agile_eval/provenance.py).
Grading results stay at **schema 2**; criterion reasons and raw judge responses
remain excluded. A fresh scorer result additionally gets
`<result-filename>.provenance.json`. Standalone scorer output is not automatically
trusted by an aggregator.

The manifest contains:

- `context`: run ID, all selected task IDs, harness revision and dirty status
  (null means unavailable, never clean), source fingerprint/inventory, per-task
  prompt/acceptance/profile/fixture-declaration and canonical-original hashes,
  grading-doctrine hash, dependency-lock hashes, available Python/package
  versions, requested model IDs, scorer and contract version.
- `models.observed` is empty in this offline mode. Copilot CLI version is explicitly
  unavailable: collection never invokes Copilot to discover a version or model.
  Package versions identify what is installed, not proof that locks were enforced;
  `check_environment.py` and `pip check` remain separate mandatory checks.
- `execution`: dry, admission blocked, sandbox not verified, no approval reference,
  execution not ready. Provenance does not grant permission to execute or score.
- `context_sha256`: SHA-256 of sorted-key, compact, ASCII JSON of `context`.
- `result_bindings`: caller-selected filename, byte SHA-256, run ID, task ID,
  canonical input identity and acceptance hash. The summary binding uses a null
  task ID and the full selected-input identity. Task skips/setup errors retain the
  full denominator once Python starts. **Python is a prelaunch prerequisite**:
  a launcher without an interpreter exits 2 with an actionable diagnostic and
  creates no artifacts. Dependency/preflight/capture failures after task selection
  retain every selected task as setup_error (ten for the complete custom suite).

**Trust boundary.** The Python runner holds the context captured at initialization.
Native credit consumption loads context against that independent digest and validates
the result sidecar against the expected run/task/acceptance, not merely against its
own adjacent manifest. `provenance.result_status` is a format-only API;
`provenance.credited_status` is the credit boundary. Missing/unknown provenance cannot
award credit. Version 1 is dry/blocked: even a correctly bound synthetic RESOLVED
payload cannot authorize positive credit. Summary finalization verifies the selected
inventory/counts and refuses unbound credits. Canonical fixture-original validation
remains repository-authoritative. Changing acceptance while retaining its criterion
count is still a different input.

SHA-256 provides integrity **against independently trusted expected context**, not
authentication against an actor rewriting that context and every file. These records
are not signed, an approval controller, proof of model observation, or an OS sandbox.
Identical result bytes have identical hashes; the provenance binding supplies the
run/task attribution, not an embedded identity in schema-2 bytes. A future verified
worker and human controller remain separate, unimplemented requirements.

**Hash scope (`harness-source-v1`).** Allowlisted source extensions
`.py/.ps1/.sh/.md/.json/.yaml/.yml/.txt` under `eval/`, `plugins/`, `scripts/`, plus
root `AGENTS.md` and explicit repository profile/instruction/marketplace files.
Text files are limited to `requirements*.txt`. Relevant untracked source is included.
Run/result directories, research, transcripts, secret/credential directories, environments,
caches, build output, known credential filenames and `.env*` are excluded; no home
directory or environment dump is read. Selected canonical fixture inputs additionally
include their declared files regardless of extension. The fingerprint is scoped
source identity, not a whole-repository archive or an assertion that ignored files
cannot affect arbitrary future tools.

The declared parent output root is pruned before traversal, including retained sibling
runs. Dedicated output trees such as `eval/custom-output` and external output roots
are supported; repository/source roots and authoritative source component trees
(including `eval/python`) cannot
be used as output exclusions. Standalone capture requires the validated
`<output-root>/<run-id>/ws/<task-id>` layout with canonical immutable inputs; its exact
result and sidecar paths are also excluded when saved elsewhere, without excluding
their parent directory. Capture precedes writing the result or native run manifest.
This does not discover historical output trees outside the declared output root.

Reads are bounded to 4 MiB per file with a 20,000-source-file inventory cap.
Provenance JSON reads also reject more than 64 nested object/array containers
(the root object counts as one) before decoding. Delimiters inside strings do
not count. This bound is explicit, not dependent on Python's recursion limit.
Traversal, symlinks/reparse points, malformed versions/hashes/statuses and unsafe
export paths fail explicitly. References from a manifest are compared, never used
to discover arbitrary files. Hashes and sanitized result metadata are retained;
arbitrary judge diagnostics are not. Existing legacy runs stay **legacy/unattributed**:
no backfill, no transcript inspection, no reproducibility claim.

## Choosing a scorer

There is **one backend**, `deepeval` (still the default). `--scorer shell` and
`--scorer both` / `-Scorer shell|both`, including `EVAL_SCORER`, are retired and
produce an actionable argument error; they are not aliases for a fake comparison.
The old `score-judge.{ps1,sh}` and `shell_judge.py` entrypoints are thin compatibility
forwarders to `deepeval/score_workspace.py`, not additional backends.

One shared domain implementation in `agile_eval.grading` validates trusted inputs and returns
`UNVERIFIED` for all valid held inputs, without importing DeepEval or invoking tools.
Invalid inputs return `SETUP_ERROR`. `AcceptanceMetric` hosts that same implementation
as a real DeepEval `BaseMetric`; native metrics require the locked DeepEval dependency
and never fall back to `object`. The strict result contract remains `0` resolved /
`1` failed / `2` partial / `3` unverified / `4` setup or judge error. Schema 2 and
dry-only provenance v1 remain unchanged; no live v2 or positive SDK loop exists.

Custom-suite setup failures exit 2; successful dry staging exits 0 independently
of the pass threshold (no score exists). SWE-bench preparation remains unwired:
its dry manifest check retains the historical exit 0 while listing every selected
task as setup_error, never as failed/resolved. It is not an execution-readiness check.

`deepeval` became the default on 2026-08-19 after an A/B over all 10 custom tasks: the judges
agreed on only 3, and on 6 of the 7 disagreements the shell judge was demonstrably wrong — **all
four of its `failed` verdicts were its own artifact-collection defects** (build output flooding the
size budget, `.github/` excluded so a workflow task could never pass, its own truncation reported
as the agent's absence). The per-task evidence is in [`baselines.md`](baselines.md).

That comparison and ADR 0015's historical shell-retention note describe the earlier
migration, not the current runtime. Reproduce the old runner source from git ref
`ccafa13e1c782220db001ac081433dca2ae1df54`; historical measured evidence remains in
`baselines.md` (the ref itself retains the live hold). Current summaries do not emit
comparison/agreement fields. Unscored percentages are `null`, not a measured 0%;
all status counts and the full selected denominator remain present.

Each task's `grading` contains claimed and normalized verdicts, criterion statuses, and
completeness; sidecar JSON retains only bounded structural fields and sanitized diagnostics.
Raw judge responses and free-form criterion reasons are not persisted or printed.
UNVERIFIED criteria cannot award resolved credit, even for a claimed RESOLVED verdict.
Historical baselines are not recomputed.

## Live evaluation safety hold

Live evaluation remains **disabled**. The credential-free, network-disabled requirement
applies to **untrusted artifact execution workers**, not to the separate model API control
plane, which necessarily needs network access and authentication. A future worker must
not access host credentials, the host filesystem or Docker socket, or external/host/control-plane
networks. Task-local loopback and database networking policy is not yet approved.

HOME redirection, temporary directories and PATH filters are **configuration hygiene,
not OS isolation**. The prior isolated Copilot configuration controlled plugin resolution;
it did not isolate host credentials, networking or filesystem access. `run-eval.*` exits
before staging or invoking a model unless `--dry-run` / `-DryRun` is selected. Dry runs
only preflight and stage fixtures; they execute no generated artifacts and certify no
worker readiness. Scorers validate workspace/canonical-baseline inputs, then return
`UNVERIFIED` without model or tool execution.

Human plan approval remains a separate mandatory gate, currently unreachable behind this
hold. Approval alone is not permission to resume live execution.
Do not remove the hold using chmod, environment variables,
prompt instructions, executable allowlists, or the offline fake-CLI tests.

## Score existing outputs with DeepEval

The operational first step is **existing-log analysis**, not launching fresh agents.
Install the pinned environment using [deepeval/README.md](deepeval/README.md#run-it).
From the repository root:

```bash
# Synthetic fixture demonstration only — NOT a benchmark of the current harness.
python eval/deepeval/report_skill_usage.py eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl --score --expect-skill fixture-skill-a --output eval/pipeline/runs/skill-fixture-summary.json

# Existing retained logs: each log must have invoked every explicitly expected skill.
python eval/deepeval/report_skill_usage.py path/to/existing/logs --score --expect-skill architecture-decision-records --output eval/pipeline/runs/skill-usage-summary.json
```

File inputs and recursive `.log`/`.jsonl` directories work. Repeat `--expect-skill`
for additional identities; choose a directory whose logs share those expectations.
The real pinned `ToolCorrectnessMetric` scores the fraction of unique expected skill
identities recorded in each trace, not merely the presence of a `skill` tool.
Exit **0** means all inputs scored 1; **1** means at least one measured failure;
**2** means argument/input/schema/setup/measurement/output error. A partial score
such as 0.5 remains a measured failure, not a setup error. JSON retains per-input
scores and errors separately; input/schema errors never award a pass.
Dry-run placeholder logs are not valid traces.

This measures **recorded invocation only**: not successful tool completion,
correct use of the skill, workspace acceptance, task quality, model identity or
authenticity of the supplied log. It does not award provenance-bound outcome
credit. No model, generated code, cache, hosted report or new agent is involved.
See the [CLI contract](deepeval/README.md#existing-output-scoring-contract) for
privacy, schema, and legacy parser-only behavior.

## How to run

Python is required before an attempt starts. Use an interpreter with the locked
PyYAML dependency for dry staging; held scorer preflight itself is stdlib-only.
The single implementation can also be invoked directly, from `eval/`:

```bash
python -I -S -B -X utf8 pipeline/run_eval.py --suite custom-eval --dry-run
```

### PowerShell (Windows / cross-platform PowerShell 7+)

```powershell
# Offline custom-eval preflight/staging
./pipeline/run-eval.ps1 -Suite custom-eval -DryRun
```

### Bash (Linux / macOS)

```bash
./pipeline/run-eval.sh --suite custom-eval --dry-run
```

Non-dry-run commands fail closed before model invocation. The mandatory human plan-approval
gate remains in force as a separate gate; the current sandbox hold blocks earlier.

### CI (on demand)

The [`Eval · pipeline offline scoring`](../.github/workflows/eval-pipeline-outcome.yml)
manual workflow defaults to **actual offline measurement**, not staging:

| Input | Default / meaning |
|---|---|
| `mode` | `offline-score`; alternatively `fixture-staging` |
| `trace_path` | `eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl` — **synthetic fixture**, not a current-harness benchmark |
| `expected_skills` | `["fixture-skill-a"]`; JSON array, each identity passed literally as a separate expectation |
| `dry_run` | `true` is mandatory in both modes. `false` fails closed before checkout/provisioning; it never substitutes an offline score for a live request |
| `suite`, `task_filter`, `pass_threshold` | Staging only; defaults `custom-eval`, `.*`, `0`. Threshold must be an integer 0–100; it does not change the skill metric's fixed **1.0** threshold |

Both modes install CPython 3.12 and the existing hash-locked wheel closure, including
PyYAML, then validate dependencies. Only trusted wheel download contacts PyPI.
There is no provider login, secret, agent/model call, generated-code execution,
SDK/runtime provisioning or remote trace download.

The default scoring step is equivalent to:

```bash
python eval/deepeval/report_skill_usage.py eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl --score --expect-skill fixture-skill-a --output eval/pipeline/runs/skill-usage-summary.json
```

For existing traces, select a repository-relative file or directory already present
in the checked-out revision and set `expected_skills`, for example
`["architecture-decision-records","read-repo-context"]`. Every selected trace gets
the same expectations. Absolute paths, missing paths, paths/symlinked log files
escaping the checkout, malformed/empty expectations and pre-existing/redirected
output paths fail closed. Paths and identities are passed as data, never shell
source. Do not put secrets in expectation labels. Gitignored developer logs are
not available on hosted runners; use the local command for those, not a remote
artifact import mechanism.

Scoring exits **0** for full coverage, **1** for measured failure/partial coverage,
and **2** for setup/schema/argument/output errors. These propagate to job failure.
The job summary explicitly distinguishes synthetic demonstration, existing traces,
staging and live refusal; **recorded invocation is not successful tool completion,
task acceptance or L2 resolved credit**. Acceptance remains `UNVERIFIED`.

Only `eval/pipeline/runs/skill-usage-summary.json` (scoring) or
`eval/pipeline/runs/*/summary.json` (staging) is uploaded, including after a failed
measurement, with seven-day retention. Raw transcripts and workspaces are not
uploaded. Missing reports are errors, never inferred scores.

The `eval-skills.yml` Ubuntu/Windows runtime-contract matrix also runs the synthetic
demonstration after dependency validation, using the command above with output
`eval/pipeline/runs/skill-fixture-summary.json`. Its unittest/pytest split and Waza
skill checks are unchanged.

The `native_only` input, native qualification job and deleted native test selectors
have been removed. Sandbox experimentation is deferred to
[#22](https://github.com/hoffe86/agile-agents/issues/22); the live hold remains.

Legacy fixture-staging outputs land in `runs/<run-id>/` where `<run-id>` is
`YYYYMMDD-HHMMSS-<suite>-<unique-suffix>`. Treat the uniqueness suffix as opaque:

```
runs/
└── 20260415-093014-custom-eval-<unique-suffix>/
    ├── task-01-csharp-minimal-api-endpoint.log
    ├── task-02-python-di-refactor.log
    ├── ...
    ├── run-provenance.json
    └── summary.json
```

The `runs/` folder is gitignored in the distribution; only `baselines.md` is committed.

## Scoring rubric (short form — full form in [`scoring-rubric.md`](pipeline/scoring-rubric.md))

| Status | Meaning |
|---|---|
| `resolved` | All acceptance criteria pass; tests green; no broken build |
| `partial` | At least one criterion passes; remaining criteria fail non-catastrophically |
| `failed` | No meaningful output, build broken, or all criteria fail |
| `unverified` | Cannot verify a criterion; no resolved credit; reasons and verified failures retained |
| `setup_error` | Fixture/setup or judge CLI/environment/contract error, not a failed agent |
| `blocked_approval` | Mandatory human plan approval cannot be received unattended |
| `skipped` | Dry-run wiring only: no agent/judge executed |

Aggregate scores reported in `summary.json` and `baselines.md`:

- **Resolved %** = resolved / total
- **Partial %** = partial / total
- **Failed %** = failed / total

Every selected task stays in the denominator. Resolved + partial + failed + unverified +
setup_error_count + blocked_approval_count + skipped must equal total.
Suite runners exit **2** for setup_error, **3** for unverified or blocked_approval,
and otherwise **0** when resolved % ≥ 60%, **1** below the threshold. Dry runs exit 0
without a score. A permissive threshold cannot make an uncertain/error run successful.

## Adding a custom task

1. `mkdir custom-eval/tasks/task-NN-<slug>`
2. Add files following the pattern of existing tasks:
   - `prompt.md` — the user-story prompt to give `dev-lead` (10-30 lines)
   - `acceptance.md` — 3-5 explicit, machine- or human-verifiable pass criteria
   - `solution-profile.yaml` — the synthetic profile context (tech stack, quality gates, etc.)
   - `inputs.json` — every pre-existing input (or an empty list), with versioned baseline files
3. Express required checks in the profile and acceptance criteria. Executable
   `score.ps1`/`score.sh` overrides are not supported. The single runner holds all
   live execution; held grading returns `UNVERIFIED` for valid inputs without a model call.
4. Validate offline staging with `-DryRun -TaskFilter task-NN`.
5. Record measured baselines only after separately approved execution work supplies
   safe isolation and human approval; a dry run is not a measurement.

## Portability notes

This harness is intentionally minimal so a downstream fork can:

- **Replace `swe-bench-subset/`** with their own external benchmark (a slice of their bug-tracker,
  internal coding interview tasks, etc.). The `tasks.json` schema is two required fields:
  `instance_id` and `repo`. `difficulty` is optional metadata.
- **Replace `custom-eval/`** with project-representative tasks, retaining valid profiles,
  declared inputs, prompts and actual numbered acceptance criteria.
- **Keep `run_eval.py` and its thin `run-eval.ps1` / `run-eval.sh` launchers**
  unchanged — they are profile-agnostic. Launchers only select Python, translate
  arguments and propagate its exit code. Task filtering uses Python regular expressions.
- **Customise `scoring-rubric.md`** for stricter or laxer pass criteria (e.g., a regulated
  project may want `resolved` to require ADR + threat model on every task).
- **Track `baselines.md` per project** — this is where the value compounds; every commit's
  delta is visible.

Offline contract tests call no models. Live agents and judges are currently blocked until
a credential-free, network-disabled OS sandbox exists; workspace commands are not run on
the host. The benchmark's native builds may also need dependencies already provisioned
once safe isolation is available.

## Scoring

There is no live agent/judge execution path. The one grading implementation returns
`UNVERIFIED` for valid held inputs without passing workspace content to an external
model. Invalid inputs are setup errors, not agent failures. The former unrestricted
CLI loop, dormant per-task executable override dispatch and shell comparison have
been removed, not moved into Python. Dropping a `score.ps1` or `score.sh` into a task
does not execute it. A future approved SDK integration must separately supply safe
execution and human approval; no diagnostic result can enable it today.

`agile_eval.prepare_inputs` stages declared originals in a sibling baseline directory. Workspace
metadata pointers and file mode bits are not trusted; the evaluator checks manifests against
canonical fixture hashes. This integrity check is not an OS access boundary, so the live
runner and scorers remain blocked. Task-10's ingress-host ambiguity and native toolchain gaps
remain `UNVERIFIED`; no static proxy is treated as a pass.

Self-check the
verdict parser with `pipeline/score-judge.ps1 -SelfTest`, `pipeline/score-judge.sh --self-test`,
or `python deepeval/score_workspace.py --self-test` (none call copilot).

## Status & limitations (be honest)

`run-eval.ps1` / `run-eval.sh` reject every non-dry-run evaluation before staging or CLI
invocation (exit 2), because no credential-free, network-disabled OS sandbox is available.
This safety hold does not waive or replace the mandatory human plan-approval gate. Dry runs
stage inputs and report ten skipped tasks, not failed work; no model or judge is invoked.

- **SWE-bench task-prep is not wired.** Future preparation needs the issue text from
  `princeton-nlp/SWE-bench_Verified` plus a checkout of the target repo at the base commit.
  Current dry manifest checks report every selected task as setup_error with a clear note.
  No live invocation helper remains: preparation alone cannot enable execution.
  Future execution is separate, explicitly approved work requiring safe isolation and
  human approval; the single runner's live HOLD applies to both suites.

Current dry preparation and held grading do not fetch datasets or call models.
Any future dataset download or agent/judge connectivity requires separate approved work.

## Related plan items

- **H2** (this folder) — measurement foundation
- **H1** — semantic localisation: re-run this harness before/after to measure file-recall lift
- **H3** — test-bar gate: re-run to measure reviewer-cycles-saved
- **H4** — cost tracking: depends on H6 events, scored alongside resolved-rate here
- **H6** — JSON event log: events appear in `runs/<run-id>/events.jsonl` once H6 lands

## Offline authorization controls

These controls do not enable live execution. ADRs 0008 and 0015, ordinary human
approval gates, dry provenance v1, grading schema 2, disabled live judging and
rejection of positive credit are unchanged.

`agile_eval.authorization` provides frozen, strictly validated records with bounded,
canonical JSON and SHA-256 digests. Unknown/missing fields, duplicate JSON keys,
type coercion, nonfinite numbers and invalid UTC timestamps are rejected. A
`PlanSubmission` includes its assessment reference but not the assessment outcome;
the independent `Assessment` binds the submission digest, avoiding a digest cycle.
Favorable advice is not approval and cannot expand capabilities.

The approved inventory always includes all ten existing task IDs. Only
`task-05-pr-description` is supported as the initial candidate; nine unsupported
tasks stay in the denominator. Task 05 reads the immutable synthetic `diff.patch`
and produces Markdown **description text only**. It cannot open a PR, modify the
depicted source, contact JIRA, alter inputs or use network/shell tools.

### Offline authorization API

Use the trusted `eval/python` source root:

```text
agile_eval.authorization:
  Identities, Budget, Operation, BatchEnvelope, PlanSubmission, Assessment,
  Decision, Readiness, JobAuthorization
  Record.from_dict / from_json / canonical_bytes / digest
  sha256(exact_plan_bytes) -> str
  evaluate(envelope, submission, assessment, *, now) -> Decision
  live_readiness() -> Readiness

  JobAuthorization(submission)
  JobAuthorization.attempt(envelope, current_binding, assessment, *,
                           expected_digest, approval_reference, now) -> Decision
  JobAuthorization.abort(reason="controller_aborted")
  JobAuthorization.state / attempts / reserved_budget / terminal_reason
```

All `now` values come from the trusted caller as UTC whole-second
`YYYY-MM-DDTHH:MM:SSZ` strings. `Identities` binds source, plugin, overlay, input
and toolchain SHA-256 values plus runtime/model IDs and capabilities; operations
bind kind, exact absolute target, actor identity and byte limit. The library does
not read native plan files or authenticate model/runtime claims on its own.

The attempt method is never an agent tool. The expected digest and approval
reference must arrive independently from human approval, not from a workspace
file or the envelope's own claim. Adjacent approval/provenance files are never
ingested. `attempt` evaluates policy internally; it does not accept a caller's
purported eligible decision.

Each job starts `UNAUTHORIZED`. A policy-evaluated attempt uses the job (`USED`);
integrity failures latch `ABORTED`. Attempt count is at most one; eligibility
reserves the full declared budget, and abort cannot refund it. No operation
becomes executable. There is no cross-job cumulative accounting, recovery,
persisted permission, per-operation grant or durable deduplication. A local
thread lock protects the single offline attempt, not an OS boundary.

```text
python -B -m unittest discover -s eval/pipeline/tests -p test_authorization.py -v
python eval/authorization.py check-readiness
```

The first command tests strict records and single-job policy without an SDK or
DeepEval. The second performs no SDK startup, credential discovery, staging or
network access and always exits **2**. Readiness stays `execution_ready: false`;
the runner unconditionally holds live execution regardless of that diagnostic's
result. These offline contracts remain for regression coverage, not as an
authorization engine for existing-log scoring.

## Deferred sandbox work

[Issue #22](https://github.com/hoffe86/agile-agents/issues/22) owns sandboxing and
the held SDK-controller experiment. Its implementation and qualification diary
are preserved at commit
[`08892b463a979bbfdaf7399d2d950cff8ff5c07c`](https://github.com/hoffe86/agile-agents/tree/08892b463a979bbfdaf7399d2d950cff8ff5c07c).
Native probes/helpers, their tests and the unused SDK dependency have been
removed from active source, not relocated into another active folder.
Tests of the retained runner's unconditional live hold remain in
`deepeval/tests/test_native_scoring.py`, including diagnostics that return success,
raise `OSError`, or time out: none may permit staging or execution-dependency imports.
Readiness import/CLI coverage remains in `pipeline/tests/test_authorization.py`.
No native qualification, runtime startup, fresh agent execution or release of
the live hold is part of existing-output scoring.

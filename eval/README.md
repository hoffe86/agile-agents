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
re-exports. The native controller still depends on authorization; preparation and
the run coordinator retain their existing responsibilities and lazy dependency boundary.

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

The [`Eval · pipeline outcome`](../.github/workflows/eval-pipeline-outcome.yml) workflow runs the harness on GitHub Actions via
`workflow_dispatch`: pick the suite, an optional task-filter regex, a pass-threshold (0-100), and a
`dry_run` toggle (**default on** — performs offline fixture preflight/staging). It posts `summary.json` to the run summary and uploads
`runs/` as an artifact.

Selecting `dry_run: false` fails closed before staging or invoking a CLI. No Copilot secret is
needed or exposed, and the ordinary harness job does not install Copilot. Live execution remains disabled
until a verified OS sandbox exists; human plan approval remains a separate mandatory gate.

The separate `native_only` boolean defaults to **false**. Setting it to **true** runs only
no-model native boundary qualification on hosted Ubuntu/Python 3.12, using the existing
hash lock (SDK 1.0.24) and publisher-managed CLI 1.0.101. Before checking host support,
the job installs only the [official Linux prerequisites](https://docs.github.com/en/copilot/how-tos/cloud-and-local-sandboxes/using-local-sandboxing#prerequisites)
using the ephemeral Ubuntu 24.04 runner's normal `sudo apt-get` provisioning:
`bubblewrap=0.9.0-1ubuntu0.3` (Noble updates/security, main) and
`slirp4netns=1.2.1-1build2` (Noble release, universe). These exact versions were
verified against Ubuntu's primary archive on 2026-10-22
([Bubblewrap](https://api.launchpad.net/1.0/ubuntu/+archive/primary/+binarypub/249852446),
[slirp4netns](https://api.launchpad.net/1.0/ubuntu/+archive/primary/+binarypub/207474824));
APT source/version policy and installed versions are logged. An unavailable pin fails
closed rather than selecting an unreviewed version. No SDK/CLI/DeepEval pins change.
The workflow checks executable availability, including `/usr/bin/python3`, but does
not invoke `bwrap` directly. [Copilot owns sandbox lifecycle and policy through
MXC](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/about-cloud-and-local-sandboxes#how-local-sandboxing-works);
[MXC uses Bubblewrap by default on Linux](https://github.com/microsoft/mxc).
No direct MXC dependency or wrapper is needed. The unchanged native driver uses
`sandbox_config` and `client.rpc.sandbox.get_host_support()` to check runtime
capabilities, and still requires actual file/network/environment canaries. Current
documentation describes the integration, not proof that the locked SDK/CLI pair
works on this host. Missing support or OS-policy denial fails the job; no
AppArmor/sysctl, setuid, or other security-policy workaround is permitted.

Run [40478427043](https://github.com/hoffe86/agile-agents/actions/runs/40478427043)
installed both pinned packages, then the former direct namespace probe failed with
`loopback: Failed RTM_NEWADDR: Operation not permitted`. The native SDK never
started. That ad hoc probe was not established as equivalent to MXC's invocation.
Removing it removes duplicated code; it does **not** resolve the host denial or
authorize a retry through the SDK or another backend. Real native validation remains
blocked until policy/prerequisites are resolved or an authorized environment is
available.

The job passes no credentials or model prompts, retains
only sanitized check results in job logs, and removes its temporary provisioning.
This mode produces no benchmark grades, percentages, or run artifacts. A passing primitive
check does **not** verify actual Stage 4/delegation fidelity or release the controller's
live hold. Keep `dry_run: true`; suite/filter/threshold inputs are not used in native mode.

Outputs land in `runs/<run-id>/` where `<run-id>` is
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

### Controller API seam for the held native adapter

Use the trusted `eval/python` source root and import `agile_eval.authorization`
and `agile_eval.native_controller`, following the existing evaluation scripts:

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

All `now` values come from the trusted controller clock as UTC whole-second
`YYYY-MM-DDTHH:MM:SSZ` strings. `Identities` binds source, plugin, overlay, input
and toolchain SHA-256 values plus runtime/model IDs and capabilities; operations
bind kind, exact absolute target, actor identity and byte limit. The native
adapter must capture the actual owned-session path and hash exact plan bytes
without newline/whitespace normalization, then supply the full current submission
again at the single offline attempt. This library does not read native plan files or authenticate
model/runtime claims on its own.

The attempt method is a **trusted controller API**, never an agent tool. The
expected digest and approval reference must arrive independently from human
approval, not from a workspace file or the envelope's own claim. Adjacent approval
and provenance files are never ingested. `attempt` evaluates policy internally;
there is no API accepting a caller's purported eligible decision.

Authorization uses one job-local state object in `agile_eval.authorization`. A local thread
lock protects its single offline attempt; callbacks have a separate async lock. There is no
pending grant, receipt, per-operation admission, database, epoch or recovery API.
The canonical envelope no longer has `grant_ttl_seconds`; old records containing
that removed field are rejected, not migrated into authority.

Each job starts `UNAUTHORIZED`. Independently authenticated approval inputs are
required for its one attempt. A policy-evaluated attempt, including blocked or
uncertain advice, uses the job (`USED`); integrity failures latch `ABORTED`.
Attempt count is at most one even if envelope limits allow more. On eligibility
the full declared budget is reserved; abort cannot refund it. Expiry is checked
against the approved envelope at that transition. No operation becomes executable.
There is no cross-job cumulative accounting or durable deduplication: another job
requires fresh independent approval, not reuse of persisted permission.

The controller must remain inaccessible to untrusted workers. In-process locks
do not prove that boundary or make native plan capture/execution atomic. A new
controller always starts unauthorized, including after invalid input, cancellation
or restart. It never restores permission from JSONL, audit, result or approval files.

### Offline verification and remaining blockers

```text
python -B -m unittest discover -s eval/pipeline/tests -p test_authorization.py -v
python eval/authorization.py check-readiness
```

The first command uses only the standard library, strict-record and single-job
policy tests, including a local thread race. It does not verify OS isolation.
The second performs no SDK import/startup, state
creation, credential discovery, staging or network access, and always exits **2**.
The authorization and native controller test modules are selected explicitly by
`python scripts/run-repo-checks.py unit`, retaining the existing unittest/pytest
split. Authorization tests need no SDK or DeepEval; controller tests use the shared
evaluation environment described in [deepeval/README.md](deepeval/README.md).

Readiness is permanently `execution_ready: false`, `state: not_ready`, with:
`live_hold`, `controller_state_isolation_unverified`,
`native_atomic_admission_unverified`, `stage4_plan_provenance_unverified`,
`delegate_model_provenance_unverified`, `credential_transport_unverified`, and
`pinned_runtime_compatibility_unverified`. The native control seam below adds
defensive callbacks, environment sanitation and runner diagnostics behind this
same permanent hold; no live execution is enabled.
No paid evaluation, live-v2 success record or positive credit is enabled by these
controls. The separately authorized dependency upgrade and bounded no-model
qualification below do not release them.

### Held native controller

`agile_eval.native_controller` is a standard-library-only adapter seam. Its
`NativeController` receives one independently bound `PlanSubmission`, the exact
owned native session/path and a dedicated owned runtime, and creates its own fresh
`JobAuthorization`. Do not supply a shared runtime. The public
`NativeSession` / `NativeRpc` / `NativePlan` protocols
mirror the SDK 1.0.24 `session.rpc.plan.read()` attribute result
(`exists`, `content`, `path`); tests use typed doubles and offline SDK contracts,
not a live runtime.

- `on_exit_plan_mode_request` checks callback and owned session IDs, awaits the
  owned native plan read, and checks the exact path and UTF-8 content SHA-256
  without newline or whitespace normalization. It never substitutes inline
  `planContent`, `summary` or `recommendedAction`. Even a matching plan returns
  `stage4_plan_provenance_unverified`: native plan capture is not semantic Stage 4
  provenance. No branch approves, uses the offline attempt, or selects `exit_only`.
- `on_pre_tool_use` explicitly denies every route, including native tools,
  delegates, unknown/unattributed calls and remote MCP. Ordinary handler failures
  latch abort, finish cleanup and **return deny**, rather than trusting an SDK
  hook exception to deny. `on_permission_request` independently rejects;
  `on_user_input_request` refuses arbitrary approval strings.
- `abort` / `on_disconnect` latch terminal state before awaiting cleanup. They
  abort the job, disconnect the session and stop only the dedicated owned runtime. Failed graceful stop
  falls back to bounded `force_stop`. Cancellation waits for cleanup and then
  propagates. Cleanup failures retain bounded codes, not exception text; even a
  failed force-stop never permits continuation. No automatic resume, retry or
  grant refund. An OS-level failure to stop remains unresolved—not proof that
  the process died.
- A session lock serializes callback work; it does not make native
  plan-read-to-callback-return-to-tool execution atomic. SDK failures before callback dispatch and alternate execution routes
  remain unverified and are among the reasons startup stays blocked.

`sanitized_runtime_spec(parent_environment, *, home, config, temp, workspace,
trusted_path)` builds an immutable environment from explicit values and only a
constrained `LANG` allowlist. It does not copy the parent's environment, mutate it,
discover credentials, create directories, or inherit user PATH/config, Git/SSH,
proxy/keychain/cloud/model credentials or Node/Python startup injection settings.
Paths and binaries must already be controller-owned/trusted. Its defensive
session options disable discovery, file hooks, host Git/cache integration and
session storage; no plugin/MCP/tool routes are enabled. This is tested
**configuration hygiene**, not verified native sandbox/network/credential isolation.
An empty tool list is not revocation.

`start_native_runtime(spec, *, github_token=None)` always returns `not_ready`
**before SDK import, client construction or startup**. Client-level token options
are rejected (including an empty string). SDK 1.0.24 `client.py` replaces inherited
environment when explicit `env` is supplied, but then injects `github_token` into
`COPILOT_SDK_AUTH_TOKEN`; sanitizing the input mapping alone cannot prevent that
leak. No per-session token, environment-secret or proxy workaround is implemented.
`sdk_callbacks(controller, opt_in=True)` is an explicit integration-only lazy
import that translates the independent rejection into `PermissionDecisionReject`;
it does not create a client and is never called by readiness or the runners.

Both non-dry runners request the shared `authorization.py check-readiness`
diagnostic and then **unconditionally exit 2**. A zero/error diagnostic status,
missing Python, plausible envelope/grant files, credentials, or `NoIsolation`
cannot unlock execution. No staging or model startup occurs. Dry-run behavior,
dry provenance v1, grading v2, disabled judge and trace requirements are unchanged.

```text
python -B -m unittest discover -s eval/pipeline/tests -p test_native_controller.py -v
```

These are callback/configuration and real-shell **unit tests**, not runtime
integration evidence. Three offline tests in this same module exercise the actual
`sdk_callbacks` factory, `PermissionDecisionReject` and `PlanReadResult` types
against SDK 1.0.24 using the shared `deepeval/requirements.lock.txt` environment.
They forbid client/process/socket creation and fail on missing or wrong SDK pins.
No runtime starts or model calls occur.

### Approved boundaries and bounded qualification (2026-10-21)

The user approved **D1** and **D2**, plus latest-stable SDK/CLI restoration and
bounded **no-model** qualification. This does not approve an evaluation run.

- **D1:** the unchanged `dev-lead` supervisor may execute only its prescribed
  `run-event-log`, `cost-budget` and applicable `test-bar-gate` orchestration
  scripts inside the native sandbox. Task-05 workers remain shell/network denied.
  Native role/session attribution must distinguish them; no blanket shell grant
  or command-prefix workaround is acceptable. Native OS enforcement for process
  tools and CLI software enforcement for built-in file operations are accepted
  trust boundaries, **not measured facts**. Workers must not access credentials,
  controller state, approval records or canonical baselines; bypass stays disabled.
- **D2:** native `exit_only`, exclusive owned session, an immutable binding to the
  actual plan, and **one separately authorized continuation** replace the earlier
  proposed native compare-digest-and-execute transaction. No autoexecution,
  competing queued turns/clients, capability broadening, or mutable-plan
  substitution is permitted. Fail-closed errors and genuine cleanup are required.
  The legacy `native_atomic_admission_unverified` code is retained as a conservative
  hold pending measurement of this approved replacement, not a demand to invent
  a nonexistent transaction. Production still has no approval/continuation branch.

SDK **1.0.24** and its publisher-selected CLI runtime **1.0.101** were restored
with the unchanged DeepEval **4.1.8** closure; exact release sources and hashes
are in [dependency maintenance](deepeval/README.md#dependency-lock-and-maintenance).
The actual selected SDK source supports `session.rpc.tools.execute(...)` without a model
turn and retains the isolated delegation tool names. Source availability is not
proof of their runtime enforcement or agent/model fidelity.

The opt-in `pipeline/tests/native_runtime_integration.py` driver reports
`missing_tools` on `native_toolset` / `native_tools_missing` failures. This is a
sorted, deduplicated subset of its fixed required names, not a raw tool inventory.
Other failure stages and successful reports do not include this field.
SDK `ToolSet` filters registered tools; it does not register them.
`get_current_metadata()` reports the session's current initialized tools.
Missing names alone do not establish a mode, catalog, authentication, or runtime
defect.

For `explicit_native_denial_required`, the driver also reports `denial_result`.
The stage identifies the probe: `native_toolset` is the `bash` request;
`native_file_denial` is the protected-file `view` request.

- `shape` is `mapping`, `object` (has `result_type`), or `other`.
- `kind` is one of the pinned SDK's `denied`, `failure`, `rejected`, `success`,
  or `timeout` values. A missing field is `absent`; any other value, including
  null, is `unrecognized`. Unknown strings and nested envelopes are not interpreted
  as denial and are never echoed.
- Only the bash probe adds `canary_file` (`present`, `absent`, `unknown`) and
  `command_execution` (`observed`, `not_observed`, `unknown`). It requests a
  bounded write of the fixed output marker to a unique file in the owned temporary
  workspace, followed by the same marker on stdout. The marker is split in the
  command text, so a command echo alone is not positive execution evidence.
  A created file or marker in `textResultForLlm` means `observed` and fails the
  check, even if the result claims denial. Missing/malformed result text or an
  unreadable file state leaves execution `unknown` unless positive evidence exists.
  **Neither `not_observed` nor file absence proves non-execution.** Passing still
  requires explicit `denied`/`rejected`, observed file absence, and no positive
  output evidence. An unreadable file state fails closed.

File-check failures retain `native_file_positive_control_failed`, `protected_canary_leaked`, or `permission_session_mismatch` through both report boundaries, with the original stage and prior passed checks.

Run [40518050911](https://github.com/hoffe86/agile-agents/actions/runs/40518050911)
passed the first four stages, then failed the allowed-file positive control;
it did not reach the protected-file read. The driver had no approval path for a
fixture read that required permission: both auto-approval flags were false and
the callback rejected every request. It had already verified `INTERACTIVE` mode
after `exit_only`, and the positive fixture existed before session creation.

The callback now returns `PermissionDecisionApproveOnce` only for a typed
`PermissionRequestRead` of the exact host-created `workspace/readable.txt`, during
that positive probe and for the owned SDK session. The requested path must match
exactly; any supplied resolved path must also match, and the fixture must still
resolve to the same regular file. Protected, outside, traversal, symlink-alias,
malformed/multiple-path and other permission requests are rejected. Managed
approval, sandbox bypass and sandbox path-grant requests are also rejected.
No directory grant, blanket read/tool approval, or sandbox policy change is used.
The approval window closes in `finally` before the protected probe.

This uses the pinned
[`PermissionRequestRead`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/session_events.py#L8493-L8550)
and
[`PermissionDecisionApproveOnce`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L32751-L32773)
contracts. The SDK supplies callback session identity in
[`session.py`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/session.py#L3401-L3452).
The public
[`permissions.paths`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L67860-L67890)
API can list exact approvals but its add operation grants a **directory**; it
does not provide an exact-file read grant setter. These three local source files
were byte-for-byte checked against official v1.0.24.

Run [40521978568](https://github.com/hoffe86/agile-agents/actions/runs/40521978568)
then passed the positive control and returned `{shape: mapping, kind: failure}`
for the protected `view` request. It failed at `native_file_denial` with
`explicit_native_denial_required`. This is not evidence of missing authentication:
the allowed native read worked. It is also not yet proof of policy denial.
If the positive marker is absent in a future run, `positive_read`
reports only `kind` (the same fixed kinds as above, plus `absent`/`unrecognized`)
and `permission` (`not_requested`, `approved`, `rejected`, or `mixed`). It never
reports response content. The positive marker-in-JSON assertion is unchanged.
The protected marker is now checked **before** the result kind, against the
original host-created marker. Returned protected content is a hard
`protected_canary_leaked` failure, including when the kind is `failure`, `denied`
or `rejected`. A changed fixture cannot change the expected marker.
Explicit denial and nonempty, all-matching permission-session assertions remain.
The latter covers all callbacks in
the check, not a requirement that protected-file denial itself invoke a callback.
Native policy may deny that request before callback dispatch.

#### Protected-file contract and bounded diagnostics

The fixture remains outside the workspace, under the exact directory supplied to
`sandbox_config.user_policy.filesystem.denied_paths`. The separate
[`PermissionPathsConfig`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L42665)
still restricts paths to the workspace, excludes the temp directory, and grants
no extra directories. Neither policy nor callback authorization is changed.

The pinned `ToolResultExpanded` schema below has `resultType`,
`textResultForLlm`, optional string `error`, and untyped `structuredContent`.
It has **no typed filesystem-policy denial code**. The public
[`managed-settings permission evaluator`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L54766)
takes URL operations; it is not a filesystem verdict API.
These contracts do not establish which result kind CLI 1.0.101 uses when
`view` hits a denied filesystem path before a permission callback.
Generic `failure` remains a failed check, not an accepted denial. No English
error-text matching, private runtime API, or invented structured code is used.

Once the protected probe starts, failures can also report `protected_read`:

| Field | Fixed values / meaning |
|---|---|
| `callback` | `not_requested`, `rejected_exact_read`, `rejected_other`, `mixed`; only callbacks during the protected probe, never the prior fixture approval |
| `callback_session` | `not_requested`, `match`, `mismatch`; a mismatch remains recorded |
| `marker` | `present`, `absent`, `unknown`; scans the serialized result, including structured fields; unknown serialization cannot pass |
| `text_shape` | `string`, `absent`, `other`, `unknown`; no text is reported |
| `allowed_directory` | `yes` / `no` from native `permissions.paths.is_path_within_allowed_directories` |
| `sandbox_blocked` | `yes` / `no` from native `sandbox.get_enforcement_status().blocked` |

The last two fields can instead be `not_run`, `unknown` (malformed value),
`timeout`, or `operation_failed`. Both inspections are public, read-only RPCs.
They run only after a protected-probe failure, each under the existing 15-second
RPC limit and 180-second outer deadline. Their errors do not replace the original
probe error. The callback window closes in `finally`, including on RPC failure.

[`Directory membership`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L67860-L67877)
is **not** a tool authorization verdict.
[`Sandbox blocked`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L15588)
means an enforcement failure permanently blocked the session; it does **not**
mean this path matched `denied_paths`. A recorded callback rejection is not proof
that the runtime applied that answer. None of these observations can turn
`failure` into a pass. They distinguish the remaining cases in one next authorized
native check without exposing raw output. The CLI's actual protected-read cause
remains **unknown**; no native run was made for this change.

Run [40528535235](https://github.com/hoffe86/agile-agents/actions/runs/40528535235)
subsequently passed the allowed read but again returned protected-read
`{shape: mapping, kind: failure}`. The protected callback was `not_requested`,
the marker was `absent`, and both `allowed_directory` and `sandbox_blocked` were
`no`. That still does not establish a denial or its cause.

The next diagnostic supplies distinct fixed synthetic `tool_call_id` values for
the positive and protected `view` requests, using the public
[`ToolsExecuteRequest`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L20692-L20717)
correlation field. The existing session callback observes public
`tool.execution_complete` events without changing its model-activity checks.
Only a protected-probe failure can add `protected_completion`:

| Field | Fixed values / meaning |
|---|---|
| `event` | `seen` / `not_seen`; whether **any** public completion was observed during the diagnostic window, not necessarily the protected call |
| `correlation` | `match` for the protected call ID; `mismatch` for a different string ID; `absent` for missing/null/empty ID; `unrecognized` for malformed ID |
| `success` | Strict JSON boolean from a matching event, otherwise `unknown`; integers and strings are not booleans |
| `error` | `present` / `absent` for a matching event's non-null error field, otherwise `unknown` |
| `code` | `present` / `absent` for a matching event's non-null error-code field, otherwise `unknown`; **never the code value** |
| `remediation` | Only pinned `RemediationAction` values: `sign_in`, `switch_account`, `show_account`, `review_sandbox_policy`, `allow_sandbox_outbound`, `rewind_conversation`; otherwise `absent` / `unrecognized` |

These are observations, **not actions to perform or permission to widen policy**.
The installed Python 1.0.24 `SessionEvent`, `ToolExecutionCompleteData`,
`ToolExecutionCompleteError` and `RemediationAction` shapes were inspected and
tested against the pinned package; the
[publisher completion/error contract](https://github.com/github/copilot-sdk/blob/v1.0.24/nodejs/src/generated/session-events.ts#L8238-L8250)
defines an open string code, not a closed denial-code allowlist. No raw message,
result, content, arguments, path, call ID, code value or metadata is retained in
the diagnostic. The outer process independently filters its keys, types and
values and prevents uncorrelated details from being attributed to the probe.

The diagnostic window starts immediately before protected execution and ends
after the existing failure-only policy inspections (or immediately on success).
It stores one fixed-size summary: the first matching completion wins, even over
earlier nonmatches; later positive, unrelated or duplicate events cannot overwrite
it. Without a match, correlation precedence is `mismatch`, `unrecognized`, then
`absent`, and error/success details remain unknown. Events before the window and
after its frozen failure snapshot are ignored.

Direct `tools.execute` RPCs may emit no public completion, or delivery may arrive
after this window. SDK 1.0.24 exposes no public completion-draining mechanism;
`get_events()` retrieves full session history, not a drain. No history collection,
extra wait, timer, polling, model request or private event dependency is added.
`not_seen` is therefore **unknown**, never evidence of denial. Internal ephemeral
`sandbox.decision` events are ignored: policy inspection is not proof that a
verdict was honored and may indicate a permitted bypass. Even a correlated
`success: false` with `review_sandbox_policy` cannot turn generic RPC `failure`
into an accepted denial. Protected-marker leakage still wins over **every**
result kind, and successful output remains unchanged.

This diagnostic is locally validated only. A repeat hosted check requires separate
publication/dispatch authorization; no new hosted evidence or root-cause claim is
made here. `live_readiness: false` and all production-execution holds remain intact.

The outer process validates every diagnostic key and value. Raw results, errors,
stdout, logs, paths and tokens are not reported. The original failure reason,
prior passed checks and cleanup rules remain in force. Successful stdout is
unchanged. For the **bash probe**, if the response is a mapping with kind `failure`,
text without the marker, and an absent file, the new field is exactly:

```json
{"denial_result":{"shape":"mapping","kind":"failure","canary_file":"absent","command_execution":"not_observed"}}
```

The installed SDK source was compared with official **v1.0.24**:
[`ToolsApi.execute`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L67665-L67674)
returns the wire result directly;
[`ToolResultExpanded`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L41785-L41866)
maps top-level `resultType` to `result_type`;
[`ToolResultType` / `ToolsExecuteRequest`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/generated/rpc.py#L20681-L20718)
lists the five kinds and describes execution of a **currently offered** tool.
The existing parser already matches that shape. This source does not establish
that requesting an unavailable `bash` tool must produce an explicit permission
denial, or that direct host RPC and agent calls have identical enforcement.
The earlier shell-result uncertainty is separate from the positive-read failure
reported by run 40518050911.
No accepted denial values, native tool grants, or live-readiness holds changed.

The driver now supplies the native activation conditions, without custom tools:

- `on_user_input_request` enables the native user-input callback and always returns
  a fixed freeform refusal; question text or offered choices cannot approve execution.
  SDK 1.0.24 serializes this as `requestUserInput` in
  [`client.py`](https://github.com/github/copilot-sdk/blob/v1.0.24/python/copilot/client.py#L2795-L2799).
- It enters and verifies `SessionMode.PLAN` **before** initializing/querying the
  current tool set. This follows the pinned
  [mode-handler example](https://github.com/github/copilot-sdk/blob/v1.0.24/python/e2e/test_mode_handlers_e2e.py);
  the later actual-plan read, digest-bound refusal and `exit_only`/no-autoexecution
  assertions are unchanged.
- `enable_skills=True` is paired with the absolute path to the existing
  `plugins/agile-agents-core/skills/trade-off-reporting` directory. The pinned
  [customization-location contract](https://github.com/github/copilot-sdk/blob/v1.0.24/docs/features/customization-locations.md#file-formats-and-precedence)
  supports a **direct `SKILL.md` bundle**, so neither a parent skill directory nor
  a new fixture/plugin is needed. The driver awaits `skills.ensure_loaded()` and
  requires `skills.list()` to contain exactly that enabled skill at its expected
  file path, without a plugin source. These are native discovery RPCs, not
  injected metadata or a custom skill provider.

Ambient configuration discovery remains off; plugin, agent, instruction and hook
roots remain empty, and the isolated builtin allowlist plus `view` is unchanged.
Explicit skill roots are not general filesystem grants, but the pinned contract
does give active local skills read-only resource access to their contributing SDK
directory. Only this one repository-controlled skill bundle is trusted here.
No skill invocation, model turn, full core-plugin loading, or harness fidelity is
claimed. Offline contracts check creation arguments against the pinned SDK signature,
refusal behavior, discovery validation and PLAN-before-metadata ordering without
creating an event loop or starting a runtime:

```console
python -B -m unittest discover -s eval/pipeline/tests -p test_native_runtime_integration.py -v
```

The configuration repair is not a successful native-host qualification: the changed
driver still requires execution in approved native CI after publication. The existing
Windows loop stall and sandbox-denial restrictions are not bypassed.
All required capabilities, denial checks, and readiness holds remain unchanged.

| Check on this Windows host | Result / evidence boundary |
|---|---|
| Official package/release identity, wheel hash, exact offline restore, `pip check` | Passed; only the SDK version changed in the Python closure |
| Selected SDK session keyword and explicit stdio connection contract | Ordinary offline regression passed; removed obsolete `enable_github_cache_store` keyword |
| Actual downloaded native executable | SDK-managed `copilot-runtime.exe` rejects `--version` with `unsupported argument '--version'`; no runtime self-reported version or handshake claimed |
| One bounded no-model SDK startup attempt | Blocked **before client construction/start**: CPython 3.11.9 Windows default asyncio loop stalls in `socket.socketpair()` → `socket.accept()`; 25-second watchdog captured the stack and terminated the owned Python child |
| Owned session creation/authentication, plugin inventory, native direct tool execution/denial | Not reached; no session created, tool dispatched, or model request sent |
| D1 supervisor/worker distinction, filesystem/network/credential protection, bypass denial | Unverified; no synthetic callback result is credited as native enforcement |
| D2 native plan binding, `exit_only`, no autoexecution, exclusive ownership, one continuation | Unverified on this pair; no plan-mode transition or continuation attempted |
| Actual delegation, selected agent/model fidelity | Unverified; deliberately no model generation or agent spawn |
| Cleanup | Qualification Python child exited; no SDK runtime/session was started. Disposable synthetic task/state removed. OS descendant inspection via `Get-CimInstance Win32_Process` was denied (`Access to a CIM resource was not available to the client`); no alternate/elevated inspection attempted |

Raw sanitized qualification data is a session-local JSON file, not a repository
proof framework or a production authorization record. The socket stall does not
identify a specific sandbox policy file: **cause/policy attribution is unknown**.
The full unit gate also stalls at the unchanged DeepEval dependency smoke's
default event-loop creation; this is not a green full-suite result. Focused package,
import-isolation and native DeepEval framework tests passed without model calls.
No tests, event-loop implementation, transport, sandbox settings or guard were
weakened to avoid the stall.

Next qualification requires the ordinary default asyncio loop to function in an
authorized environment, then real native checks of D1/D2. Additionally, the
selected SDK's `SandboxConfig` documentation says the runtime reads credential
hosts but ignores `enabled` and other policy fields supplied by the host. Therefore
neither that object nor `sandbox.get_enforcement_status()` (managed-policy status
only) attests OS enforcement. Establish the native host's enforcement capability
before permitting tools; do not substitute a custom host/proxy or remote TCP.
All readiness blockers remain in force.

**CI wiring:** `.github/workflows/eval-skills.yml` runs both suites as separate
steps in its `runtime-contracts` job, on the `ubuntu-latest` and `windows-latest`
matrix entries, after the pipeline workflow regression step:
`python -m unittest discover -s eval/pipeline/tests -p test_authorization.py -v`
and
`python -m unittest discover -s eval/pipeline/tests -p test_native_controller.py -v`.
This describes the configured workflow, not a verified successful Linux CI run.

Restart/rerun requires fresh trusted approval with an independently supplied digest
and approval reference. These are references, not credentials or an authenticator:
the caller must authenticate their source, not copy them from an envelope.
Credential transport, actual-plan authorization and native execution remain
unverified; environment sanitation is configuration hygiene, not sandbox isolation.

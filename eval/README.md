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

One folder per **unit of evaluation** — the thing being graded — with everything shared
at the root:

```
eval/
├── README.md          this file
├── baselines.md       every tier's numbers, in one place
├── pipeline/          grades RUNS    — L0/L1/L2 (ADR 0008)
│   ├── trajectory/    L0 · process conformance over the event log (free, gating)
│   ├── custom-eval/   L2 · framework-representative tasks
│   ├── swe-bench-subset/  L2 · external comparable benchmark
│   └── run-eval.{ps1,sh}, score-judge.{ps1,sh}, scoring-rubric.md, references/
└── skills/            grades SKILLS  — S0/S1/S2 (ADR 0014)
    ├── s0-routing/    should a prompt reach this skill (offline, free)
    ├── s1-invocation/ did the agent actually invoke it (model)
    └── s2-efficacy/   is the outcome better with it than without (2× model)
```

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
5. Writes `summary.json`; measured baselines are recorded manually in `baselines.md`.

## Choosing a scorer

When live evaluation is restored, tasks without a deterministic `score.ps1` / `score.sh`
will use the selected LLM judge. While the safety hold is active, every scorer returns
`UNVERIFIED` without a model call. Select the scorer with `--scorer` / `-Scorer` (or
`EVAL_SCORER`):

| Value | Judge | Behaviour |
|---|---|---|
| `deepeval` (default) | `eval/deepeval` | Returns `UNVERIFIED` without invoking a model or host tool. |
| `shell` | `score-judge.{ps1,sh}` | Returns `UNVERIFIED` without invoking a model or host tool. |
| `both` | both | Records matching `UNVERIFIED` outcomes; neither scorer executes workspace content. |

All three share a strict structured contract (`0` resolved / `1` failed / `2` partial /
`3` unverified / `4` setup or judge error). Both native twins delegate parsing and safe
artifact collection to Python; they no longer infer builds from source plausibility.

`deepeval` became the default on 2026-08-19 after an A/B over all 10 custom tasks: the judges
agreed on only 3, and on 6 of the 7 disagreements the shell judge was demonstrably wrong — **all
four of its `failed` verdicts were its own artifact-collection defects** (build output flooding the
size budget, `.github/` excluded so a workflow task could never pass, its own truncation reported
as the agent's absence). The per-task evidence is in [`baselines.md`](baselines.md).

`both` is how that migration was evidenced rather than asserted. While comparing, the **shell
judge stays authoritative** — a disagreement must not quietly move the headline score during
the very run that is measuring disagreement. Agreement is written to `summary.json` as
`scorer_comparison` (per task) and `scorer_agreement_pct`, and every disagreement is named
individually in the console output, because an aggregate rate hides the one task worth
looking at.

Each task's `grading` contains claimed and normalized verdicts, criterion statuses, and
completeness; sidecar JSON retains only bounded structural fields and sanitized diagnostics.
Raw judge responses and free-form criterion reasons are not persisted or printed. Neither judge
can award resolved credit for its own UNVERIFIED criteria, even when it claims RESOLVED.
A verified shell outcome remains authoritative when the other judge is uncertain, with
that disagreement explicitly recorded. Historical baselines are not recomputed.

## Live evaluation safety hold

Live evaluation is **disabled** until a verified OS sandbox provides credential-free,
network-disabled process isolation for both the agent and judge. The prior isolated Copilot
configuration only controlled plugin resolution; it did not isolate host credentials,
network access, or filesystem permissions. `run-eval.*` exits before staging or invoking a
model unless `--dry-run` / `-DryRun` is selected. Dry runs remain available for local fixture
preflight and staging. Do not remove this hold by relying on chmod, environment variables,
prompt instructions, or an executable allowlist.

## How to run

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
needed or exposed, and the workflow does not install Copilot. Live execution remains disabled
until a verified OS sandbox exists; human plan approval remains a separate mandatory gate.

Outputs land in `runs/<run-id>/` where `<run-id>` is `YYYYMMDD-HHMMSS-<suite>`:

```
runs/
└── 20260415-093014-custom-eval/
    ├── task-01-csharp-minimal-api-endpoint.log
    ├── task-02-python-di-refactor.log
    ├── ...
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
3. After a verified sandbox is available, the default LLM judge is intended to score it against `acceptance.md`; today it returns `UNVERIFIED` without a model call.
   Add an optional `score.ps1`/`score.sh` only if the task needs a deterministic build/test.
4. Re-run with `-TaskFilter task-NN`.
5. Once stable, append a row to `baselines.md`.

## Portability notes

This harness is intentionally minimal so a downstream fork can:

- **Replace `swe-bench-subset/`** with their own external benchmark (a slice of their bug-tracker,
  internal coding interview tasks, etc.). The `tasks.json` schema is two required fields:
  `instance_id` and `repo`. `difficulty` is optional metadata.
- **Replace `custom-eval/`** with project-representative tasks, retaining valid profiles,
  declared inputs, prompts and actual numbered acceptance criteria.
- **Keep `run-eval.ps1` / `run-eval.sh`** unchanged — they are profile-agnostic.
- **Customise `scoring-rubric.md`** for stricter or laxer pass criteria (e.g., a regulated
  project may want `resolved` to require ADR + threat model on every task).
- **Track `baselines.md` per project** — this is where the value compounds; every commit's
  delta is visible.

Offline contract tests call no models. Live agents and judges are currently blocked until
a credential-free, network-disabled OS sandbox exists; workspace commands are not run on
the host. The benchmark's native builds may also need dependencies already provisioned
once safe isolation is available.

## Scoring

After a successful `dev-lead` run, a sandboxed harness would score the produced workspace
against `acceptance.md`. Until that sandbox exists, both current judge entry points return
`UNVERIFIED` without invoking Copilot or passing workspace content to an external model.
Their offline parsers and result contracts remain testable:

1. **Default — LLM judge.** Two are available; see *Choosing a scorer* above.
   - `shell` and `deepeval` remain compatibility entry points, but neither executes a judge.
     Both report each criterion as `UNVERIFIED` until a real OS sandbox is supplied.
     The parser contract still rejects malformed or incomplete verdicts and persists only
     bounded structural results; raw model responses are never printed or written.
2. **Override — deterministic per-task scorer.** Drop a `score.ps1` (pwsh) or `score.sh` (bash) in
   the task folder and it takes precedence over both judges. Use this when acceptance needs a real
   build/test rather than a judgement (e.g. `dotnet build` / `dotnet test`, `bicep build`). It runs
   in the task workspace and retains `0 / 1 / 2` resolved/failed/partial, plus explicit
   `3` unverified; other errors map to setup_error. Default judges additionally require
   structured completeness, rechecked by the runners.

`prepare_inputs.py` stages declared originals in a sibling baseline directory. Workspace
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

- **SWE-bench task-prep is not wired.** Running a SWE-bench instance needs the issue text from
  the `princeton-nlp/SWE-bench_Verified` dataset plus a checkout of the target repo at the base
  commit. Until that prep exists, `swe-bench-subset` tasks report setup_error with a clear note. The
  invocation helper is shared, so wiring prep is the only remaining work for that suite.

For air-gapped projects the harness has no runtime network dependency beyond the SWE-bench data
download (mirrorable internally) and whatever the agent + judge fetch.

## Related plan items

- **H2** (this folder) — measurement foundation
- **H1** — semantic localisation: re-run this harness before/after to measure file-recall lift
- **H3** — test-bar gate: re-run to measure reviewer-cycles-saved
- **H4** — cost tracking: depends on H6 events, scored alongside resolved-rate here
- **H6** — JSON event log: events appear in `runs/<run-id>/events.jsonl` once H6 lands

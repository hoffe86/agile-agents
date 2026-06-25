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

## Methodology

Two evaluation suites, both runnable through the same harness:

| Suite | Source | Size | Purpose |
|---|---|---|---|
| `swe-bench-subset/` | A 25-task stratified slice of [SWE-bench Verified](https://www.swebench.com/verified.html) | 25 tasks across 8 repos × 3 difficulty bands | External, comparable-to-literature benchmark |
| `custom-eval/` | Hand-written framework-representative tasks | 10 tasks covering C#, Python, Bicep, GHA, Helm, ADRs, threat modelling | Internal, breadth-of-framework benchmark |

For each task the harness:

1. Loads the task prompt + (for custom-eval) `solution-profile.yaml` context.
2. Invokes `dev-lead` once with the prompt (TODO — see *Limitations* below).
3. Captures stdout/stderr + any produced artefacts.
4. Scores the run against the rubric in [`scoring-rubric.md`](./scoring-rubric.md):
   - **resolved** — all acceptance criteria pass
   - **partial** — some criteria pass, none failed catastrophically (no broken build)
   - **failed** — nothing meaningful produced or build broken
5. Appends the run to `baselines.md`.

## How to run

### PowerShell (Windows / cross-platform PowerShell 7+)

```powershell
# Full SWE-bench subset
./run-eval.ps1 -Suite swe-bench-subset

# Single custom-eval task
./run-eval.ps1 -Suite custom-eval -TaskFilter 'task-03'

# All custom-eval tasks matching a regex
./run-eval.ps1 -Suite custom-eval -TaskFilter 'bicep|helm'
```

### Bash (Linux / macOS)

```bash
./run-eval.sh --suite swe-bench-subset
./run-eval.sh --suite custom-eval --task-filter 'task-03'
```

### CI (on demand)

The [`Run eval`](../.github/workflows/eval.yml) workflow runs the harness on GitHub Actions via
`workflow_dispatch`: pick the suite, an optional task-filter regex, and a pass-threshold. It
posts `summary.json` to the run summary and uploads `runs/` as an artifact. It is **manual and
non-gating** while the runner is a placeholder (see *Limitations*); add `push` / `pull_request`
triggers and raise the threshold once the real `dev-lead` invocation lands.

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

## Scoring rubric (short form — full form in [`scoring-rubric.md`](./scoring-rubric.md))

| Status | Meaning |
|---|---|
| `resolved` | All acceptance criteria pass; tests green; no broken build |
| `partial` | At least one criterion passes; remaining criteria fail non-catastrophically |
| `failed` | No meaningful output, build broken, or all criteria fail |

Aggregate scores reported in `summary.json` and `baselines.md`:

- **Resolved %** = resolved / total
- **Partial %** = partial / total
- **Failed %** = failed / total

The harness exits **0** when resolved % ≥ 60% on the suite, **1** otherwise (configurable via
`-PassThreshold` in `run-eval.ps1`).

## Adding a custom task

1. `mkdir custom-eval/tasks/task-NN-<slug>`
2. Add three files following the pattern of existing tasks:
   - `prompt.md` — the user-story prompt to give `dev-lead` (10-30 lines)
   - `acceptance.md` — 3-5 explicit, machine- or human-verifiable pass criteria
   - `solution-profile.yaml` — the synthetic profile context (tech stack, quality gates, etc.)
3. Re-run with `-TaskFilter task-NN`.
4. Once stable, append a row to `baselines.md`.

## Portability notes

This harness is intentionally minimal so a downstream fork can:

- **Replace `swe-bench-subset/`** with their own external benchmark (a slice of their bug-tracker,
  internal coding interview tasks, etc.). The `tasks.json` schema is two required fields:
  `instance_id` and `repo`. `difficulty` is optional metadata.
- **Replace `custom-eval/`** entirely with project-representative tasks. The folder convention
  (`task-NN-<slug>/{prompt.md, acceptance.md, solution-profile.yaml}`) is the only contract.
- **Keep `run-eval.ps1` / `run-eval.sh`** unchanged — they are profile-agnostic.
- **Customise `scoring-rubric.md`** for stricter or laxer pass criteria (e.g., a regulated
  project may want `resolved` to require ADR + threat model on every task).
- **Track `baselines.md` per project** — this is where the value compounds; every commit's
  delta is visible.

For air-gapped projects, the harness has **no network dependencies** at runtime. The only
network-dependent step is the initial download of SWE-bench Verified test data, which adopters
can mirror internally.

## Limitations (be honest)

The harness skeleton in `run-eval.ps1` / `run-eval.sh` currently writes a **placeholder
invocation** (a `# TODO` comment) instead of actually shelling out to `copilot --agent dev-lead`.
The Copilot CLI invocation contract for non-interactive agent runs is still being finalised
(see GitHub Copilot CLI docs); once stable, replace the TODO block in both scripts with the
real subprocess call. The folder structure, manifest format, and scoring rubric are designed
so that swap is a localised change.

## Related plan items

- **H2** (this folder) — measurement foundation
- **H1** — semantic localisation: re-run this harness before/after to measure file-recall lift
- **H3** — test-bar gate: re-run to measure reviewer-cycles-saved
- **H4** — cost tracking: depends on H6 events, scored alongside resolved-rate here
- **H6** — JSON event log: events appear in `runs/<run-id>/events.jsonl` once H6 lands

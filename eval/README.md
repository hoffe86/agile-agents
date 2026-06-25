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
./run-eval.sh --suite custom-eval --task-filter 'task-03'
./run-eval.sh --suite custom-eval --dry-run     # print the copilot command per task; no auth/credits
```

`custom-eval` invokes `dev-lead` for real: it reads each task's `prompt.md`, seeds a fresh
workspace with the task's `solution-profile.yaml`, and runs

```
copilot -p <prompt> --agent dev-agents:dev-lead --plugin-dir <repo> --allow-all-tools \
        --no-ask-user --output-format json -C <workspace> --add-dir <workspace>
```

`--plugin-dir <repo>` loads this repo as a local plugin (named `dev-agents` from
`.github/plugin/plugin.json`), so the supervisor agent is addressed **plugin-namespaced** as
`dev-agents:dev-lead` — bare `dev-lead` errors `No such agent`. No prior
`copilot plugin install` is needed. The CLI must be installed and authenticated (`copilot
login`); use `--dry-run` to validate the wiring without either.

### CI (on demand)

The [`Run eval`](../.github/workflows/eval.yml) workflow runs the harness on GitHub Actions via
`workflow_dispatch`: pick the suite, an optional task-filter regex, a pass-threshold, and a
`dry_run` toggle (**default on** — renders the per-task command without auth/credits). It posts
`summary.json` to the run summary and uploads `runs/` as an artifact. It is **manual and
non-gating**; a real run (`dry_run: false`) requires a Copilot-authenticated runner. Add
`push` / `pull_request` triggers and raise the threshold once acceptance scoring lands.

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

## Status & limitations (be honest)

`run-eval.ps1` / `run-eval.sh` **invoke `dev-lead` for real** on the `custom-eval` suite
(`copilot --agent dev-agents:dev-lead --plugin-dir <repo>`). Two pieces are still open:

1. **Acceptance scoring is opt-in.** After a successful run the harness looks for a per-task
   scorer — `score.ps1` (pwsh) or `score.sh` (bash) in the task folder — and maps its exit code
   to a status: `0 → resolved`, `2 → partial`, anything else → `failed`. The scorer runs in the
   task workspace and checks `acceptance.md` (e.g. `dotnet build` / `dotnet test`, file
   assertions). **With no scorer present the task is recorded `failed` with a `needs-scoring`
   note** — the harness never credits a pass it didn't verify, so baselines stay honest. Adding
   scorers is the next increment; the rubric's "bias toward failed when unverifiable" guidance
   is encoded here.
2. **SWE-bench task-prep is not wired.** Running a SWE-bench instance needs the issue text from
   the `princeton-nlp/SWE-bench_Verified` dataset plus a checkout of the target repo at the base
   commit. Until that prep exists, `swe-bench-subset` tasks fail with a clear note. The
   invocation helper is shared, so wiring prep is the only remaining work for that suite.

For air-gapped projects the harness has no runtime network dependency beyond the SWE-bench data
download (mirrorable internally) and whatever the agent itself fetches.

## Related plan items

- **H2** (this folder) — measurement foundation
- **H1** — semantic localisation: re-run this harness before/after to measure file-recall lift
- **H3** — test-bar gate: re-run to measure reviewer-cycles-saved
- **H4** — cost tracking: depends on H6 events, scored alongside resolved-rate here
- **H6** — JSON event log: events appear in `runs/<run-id>/events.jsonl` once H6 lands

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

## Eval layers

This outcome eval is the **top** of a layered pyramid ([ADR 0008](../docs/adr/0008-layered-evaluation-strategy.md)):

| Layer | What it grades | Cost | Where |
|---|---|---|---|
| **L0** trajectory | *how* a run executed (RPI process conformance over the event log) | zero-credit, deterministic, gating | [`trajectory/`](trajectory/README.md) |
| **L1** review-detection | the Review phase (seeded-defect recall/precision) | medium | planned (ADR 0008) |
| **L2** outcome | *what* a run produced (acceptance vs. artifact) | credit-heavy, manual | this folder |

L0 runs free on every push/PR and catches process failures L2 is blind to; L2 (below) is the
end-to-end integration checkpoint.

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
copilot -p <prompt> --agent agile-agents-core:dev-lead --plugin-dir <repo>/plugins/agile-agents-core --allow-all-tools \
        --no-ask-user --output-format json -C <workspace> --add-dir <workspace>
```

`--plugin-dir <repo>/plugins/agile-agents-core` loads the plugin folder as a local plugin (named
`agile-agents-core` from its `.github/plugin/plugin.json`), so the supervisor agent is addressed
**plugin-namespaced** as
`agile-agents-core:dev-lead` — bare `dev-lead` errors `No such agent`. No prior
`copilot plugin install` is needed. The CLI must be installed and authenticated (`copilot
login`); use `--dry-run` to validate the wiring without either.

### CI (on demand)

The [`Run eval`](../.github/workflows/eval.yml) workflow runs the harness on GitHub Actions via
`workflow_dispatch`: pick the suite, an optional task-filter regex, a pass-threshold, and a
`dry_run` toggle (**default on** — renders the per-task command without auth/credits, so the
default dispatch is a free wiring check). It posts `summary.json` to the run summary and uploads
`runs/` as an artifact.

**To actually execute the agents in CI (`dry_run: false`):**

1. Create a **fine-grained personal access token** with the **Copilot Requests** account
   permission (user-owned — see
   [Authenticating Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli#authenticating-with-a-personal-access-token)).
2. Add it as the repository secret **`COPILOT_CLI_TOKEN`**.
3. Dispatch with `dry_run` **unchecked**. The job then installs the Copilot CLI
   (`npm install -g @github/copilot`) and authenticates with the token.

A real run **consumes Copilot credits and is slow** — it executes the full multi-agent pipeline
per task, and both the `dev-lead` run *and* the LLM judge call `copilot`. Use `task_filter` to
limit scope (the job has a 180-minute timeout). If `dry_run: false` is selected without the
secret, the job fails fast with a clear message rather than silently skipping. The eval is
designed as a **local/manual measurement tool first** — running `run-eval.*` on your own
authenticated machine is the cheaper primary path; CI real-runs are for shared, reproducible
checkpoints. It stays **non-gating**; add `push` / `pull_request` triggers and raise the
threshold once you trust the scores.

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
3. The default LLM judge scores it against `acceptance.md` automatically — no scorer to write.
   Add an optional `score.ps1`/`score.sh` only if the task needs a deterministic build/test.
4. Re-run with `-TaskFilter task-NN`.
5. Once stable, append a row to `baselines.md`.

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

## Scoring

After a successful `dev-lead` run the harness scores the produced workspace against the task's
`acceptance.md` and maps the result to `resolved` / `partial` / `failed` (exit `0` / `2` / else):

1. **Default — LLM judge.** [`score-judge.ps1`](score-judge.ps1) / [`score-judge.sh`](score-judge.sh)
   collect the files the agent produced (excluding the seeded `solution-profile.yaml`), fill the
   shared grading prompt in [`references/judge-prompt.md`](references/judge-prompt.md) with the
   acceptance criteria + those artifacts, and ask `copilot` for a verdict. An unparseable or empty
   verdict, or no produced files, scores `failed` — the judge never inflates the score. This
   automates the rubric's "human reviewer checks the criteria" path for narrative tasks (ADR, PR
   description, threat model) and source-level checks for code tasks.
2. **Override — deterministic per-task scorer.** Drop a `score.ps1` (pwsh) or `score.sh` (bash) in
   the task folder and it takes precedence over the judge. Use this when acceptance needs a real
   build/test rather than a judgement (e.g. `dotnet build` / `dotnet test`, `bicep build`). It runs
   in the task workspace and uses the same `0 / 2 / else` exit-code contract.

The judge needs `copilot` installed and authenticated, same as the run itself. Self-check the
verdict parser with `score-judge.ps1 -SelfTest` / `score-judge.sh --self-test` (no copilot call).

## Status & limitations (be honest)

`run-eval.ps1` / `run-eval.sh` **invoke `dev-lead` for real** on the `custom-eval` suite
(`copilot --agent agile-agents-core:dev-lead --plugin-dir <repo>/plugins/agile-agents-core`) and score it (above). One piece is
still open:

- **SWE-bench task-prep is not wired.** Running a SWE-bench instance needs the issue text from
  the `princeton-nlp/SWE-bench_Verified` dataset plus a checkout of the target repo at the base
  commit. Until that prep exists, `swe-bench-subset` tasks fail with a clear note. The
  invocation helper is shared, so wiring prep is the only remaining work for that suite.

For air-gapped projects the harness has no runtime network dependency beyond the SWE-bench data
download (mirrorable internally) and whatever the agent + judge fetch.

## Related plan items

- **H2** (this folder) — measurement foundation
- **H1** — semantic localisation: re-run this harness before/after to measure file-recall lift
- **H3** — test-bar gate: re-run to measure reviewer-cycles-saved
- **H4** — cost tracking: depends on H6 events, scored alongside resolved-rate here
- **H6** — JSON event log: events appear in `runs/<run-id>/events.jsonl` once H6 lands

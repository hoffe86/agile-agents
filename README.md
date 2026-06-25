# dev-agents

An autonomous software-development **agent suite** for the GitHub Copilot CLI, packaged as
an installable plugin. It is an **RPI pipeline** — **R**esearch → **P**lan → **I**mplement →
**R**eview — of 11 specialist agents (1 supervisor + 4 authors + 5 reviewers + a
backlog-manager) plus 52 skills, with up-front arc42/C4 + ADR conformance, multi-lens review,
and an eval/cost layer.

## Install

```shell
copilot plugin marketplace add hoffe86/agent
copilot plugin install dev-agents@hoffe86-agent-marketplace
```

Or straight from the repo root:

```shell
copilot plugin install hoffe86/agent
```

The plugin ships `agents/` and all `skills/` (repo-scope + user-scope) — installing it makes
the whole suite available in the CLI. Per-project config (`solution-profile.yaml`) is a
one-file copy into your target repo's `.github/` (see [Solution profile](#solution-profile)).

## What you get

**11 agents** (`agents/`) — 1 supervisor + 4 authors + 5 reviewers + backlog-manager:

| Role | Agent | Purpose |
|------|-------|---------|
| Supervisor | `dev-lead` | Orchestrates the RPI pipeline (Research → Plan → Implement → Review) across architect, backlog-manager, coding, testing, and review with gates |
| Author | `architect` | Read-only/advisory: serves the Research phase — verifies the change fits the prepared concept (arc42/C4) + accepted ADRs, cites them, reports ADR gaps; never authors ADRs |
| Author | `coding` | Implements features/fixes (C# / Python) |
| Author | `testing` | Writes & runs tests (xUnit/NUnit/MSTest/TUnit, pytest) |
| Author | `infrastructure` | Bicep, Terraform, Helm/Kustomize, CI/CD pipelines |
| Backlog | `backlog-manager` | Creates / improves / reviews tracker work items (ADO, GitHub, Jira, Linear); in the Plan phase materialises `dev-lead`'s task breakdown as child work items linked to the parent story |
| Reviewer | `review` | Read-only orchestrator; merges all review lenses |
| Reviewer | `security-review` | OWASP, CWE, NIST SSDF, MS SDL, MCSB, OWASP LLM Top 10 |
| Reviewer | `architecture-review` | arc42, C4, WAF, AAC, microservices.io, DDD, ISO 25010 |
| Reviewer | `infrastructure-review` | WAF, AVM, CAF, CIS Azure, OIDC, SLSA |
| Reviewer | `test-review` | xUnit Test Patterns, Google Testing, Fowler test pyramid |

**47 repo-scope skills** (`skills/`) — 21 hand-written + 26 vendored from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills)
(intermixed flat). Includes `read-repo-context` — the foundation skill every agent loads first
— and `reviewer-read-only-rules`, the defence-in-depth contract every review agent loads. See
[`skills/VENDORED.md`](skills/VENDORED.md) for the vendored index.

**5 user-scope skills** (`user/skills/`) — referenced by every agent: `working-style`,
`trade-off-reporting`, `code-review`, `cloud-native-patterns`, `azure-drawio-mcp-diagramming`.
Bundled into the plugin.

## How it works — the RPI pipeline

`dev-lead` is the supervisor. It drives a single, already-prepared user story through four
phases — **R**esearch → **P**lan → **I**mplement → **R**eview — delegating each phase to
specialist agents, gating their output, and reporting one Definition-of-Done verdict. The
arc42 / C4 concept and the accepted ADRs are authored **up-front by humans**; the pipeline
conforms to them and never writes them — a missing decision is escalated, not invented.

```
Intake → Research → Plan → Create tasks → ⛔ HUMAN PLAN APPROVAL ⛔ → Implement → Test-Bar Gate → Review → Done
```

| Phase | What happens | Agents | Hand-off block |
|---|---|---|---|
| **Intake** | `dev-lead` captures the Definition of Done, out-of-scope, the **parent story id** (when creating tasks), confirms the `solution-profile.yaml`, and mints the run id. | `dev-lead` | — |
| **Research** | Read-only verification against the prepared concept + accepted ADRs: confirm the story is implementable, verify codebase / APIs / patterns, surface any ADR gap. Lightweight (`dev-lead` reads) or delegated to `architect` when scope warrants a new boundary / dependency / trade-off. | `dev-lead`, `architect` | `ARCHITECTURE DESIGN COMPLETE` |
| **Plan** | Decompose the story into meaningful, independently-implementable **tasks**, each with its own acceptance criteria + a short approach note. | `dev-lead` | — |
| **Create tasks** | `backlog-manager` creates one child work item per task, **linked to the parent story** (provisional, tagged `pending-approval`), records the overall approach as a comment on the parent, and returns the task list. The tracker is the source of truth; local handover files are an ephemeral, gitignored cache. Gated by `backlog.create_tasks`. | `backlog-manager` | `TASKS PLANNED` |
| **⛔ Plan approval** | The **only mandatory human checkpoint** — it fires **after** the tasks exist so the human reviews concrete, linked work items. Approve → tags removed, autonomous run begins; Adjust → tasks revised; Cancel → provisional tasks cleaned up. | human | — |
| **Implement** | Coding / IaC delivers each task inside the approved plan; testing covers the change to the declared discipline. A conditional design-approval gate fires first if Research introduced a new dependency / boundary / ADR gap. | `coding`, `infrastructure`, `testing` | `IMPLEMENTATION COMPLETE`, `INFRASTRUCTURE COMPLETE`, `TESTS COMPLETE` |
| **Test-Bar Gate** | Deterministic lint → typecheck → unit-test gate before reviewers spend tokens; loops back to `coding` on fail (max 2 retries). | `dev-lead` (skill: `test-bar-gate`) | — |
| **Review** | Multi-lens review (security / architecture / infra / test) merged into one verdict, validated against the research findings and the planned acceptance criteria. | `review` (+ `security-review`, `architecture-review`, `infrastructure-review`, `test-review`) | `REVIEW COMPLETE` |
| **Done** | `dev-lead` consolidates trade-offs, reports outcome vs Definition of Done, and (when shipping) drives `pr-description` / `release-notes`. | `dev-lead` | — |

After the plan is approved, the run is **autonomous** — it stops only on a defined stop
condition (ambiguity, gate failure surviving one retry, scope change, destructive action,
missing secret, tracker-write failure, missing parent story id, or a ❌ Block review verdict).
Two cross-cutting skills ride every transition: `run-event-log` (one JSONL event per stage /
dispatch / gate) and `cost-budget` (a checkpoint after every stage, hard-stopping on envelope
breach).

### Tracker integration

The work-item tracker is the **source of truth** for the plan — not the local filesystem.
`backlog-manager` is the only agent that writes to it; every other agent treats it as
read-only context. Which tracker (Azure DevOps, GitHub Issues, Jira, Linear) is declared once
in `solution-profile.yaml` under `backlog.system` + `backlog.url`. Task creation is gated by
`backlog.create_tasks` (default `false`); when off, the plan stays in-conversation.

## Quality, eval & cost

### Eval harness (`eval/`)

The eval harness is the suite's **measurement frame** — it makes quality a number, not a vibe,
so two questions have evidence-based answers: *is the suite getting better or worse over time?*
and *did change X actually help?* (run before/after, compare the delta). Quantitative
measurement is the foundation every other quality lever is judged against.

**Two suites, one runner:**

| Suite | Source | Size | Answers |
|---|---|---|---|
| `swe-bench-subset/` | Stratified slice of [SWE-bench Verified](https://www.swebench.com/verified.html) | 25 tasks · 8 repos · 3 difficulty bands | External, comparable-to-literature score |
| `custom-eval/` | Hand-written framework-shaped tasks (C#, Python, Bicep, GHA, Helm, ADR, threat-model) | 10 tasks | Internal, breadth-of-framework score |

**Metrics.** Every task scores one of three statuses; SWE-bench mirrors the upstream definition
so numbers stay comparable to the public leaderboard:

| Status | Meaning | SWE-bench equivalent |
|---|---|---|
| ✅ `resolved` | All acceptance criteria met; build green; tests green | All `FAIL_TO_PASS` pass **and** no `PASS_TO_PASS` regression |
| 🟡 `partial` | ≥1 criterion met; remaining failures non-catastrophic (artefact still compiles/runs) | Some `FAIL_TO_PASS` pass; no `PASS_TO_PASS` regression |
| ❌ `failed` | No criterion met, build broken, or a test regressed | Patch doesn't apply, build broken, or `PASS_TO_PASS` regresses |

Per run the harness writes `summary.json` with absolute counts and the derived rates —
**resolved % / partial % / failed %** (each = count ÷ total). **Resolved %** is the headline
metric; the runner exits `0` when `resolved% ≥ pass-threshold` (default `60`), `1` otherwise, so
it can gate CI. Every run appends a row to [`eval/baselines.md`](eval/baselines.md) — the
committed trend line; diff against it after any non-trivial agent or skill change. Full
definitions in [`eval/scoring-rubric.md`](eval/scoring-rubric.md); methodology and the
add-a-task contract in [`eval/README.md`](eval/README.md); composition rationale in
[ADR 0002](docs/adr/0002-self-benchmarking-harness-composition.md).

**Run it** locally with `eval/run-eval.ps1` (Windows) / `eval/run-eval.sh` (POSIX), or on demand
via the [`Run eval`](.github/workflows/eval.yml) workflow (`workflow_dispatch` → pick suite,
task-filter, threshold; `summary.json` lands in the run summary and `eval/runs/` is uploaded as
an artifact).

> **Status:** the runner currently writes a **placeholder** result per task (scores every task
> `failed`) — the non-interactive `dev-lead` invocation is still a TODO pending the Copilot CLI
> agent-run contract. The plumbing, metrics, and scoring are exercisable end-to-end today; only
> the agent call is stubbed. The workflow is therefore manual and non-gating until that lands.

### `model_tier` frontmatter convention
Each agent declares a tier so the orchestrator can pick the right model (light = high-volume
orchestration, mid = mechanical authoring, heavy = deep multi-file reasoning).

| Agent | Tier |
|---|---|
| `dev-lead` | light |
| `coding`, `infrastructure`, `testing`, `backlog-manager` | mid |
| `architect`, `review`, `architecture-review`, `security-review`, `infrastructure-review`, `test-review` | heavy |

### AGENTS.md generation (`scripts/`)
`scripts/generate-agents-md.ps1` / `.sh` produces a portable [`AGENTS.md`](AGENTS.md) (per the
[agents.md](https://agents.md) standard) from `solution-profile.yaml` + the agent/skill
frontmatter. The folder→agent mapping lives in
[`docs/AGENTS-MD-MAPPING.md`](docs/AGENTS-MD-MAPPING.md). It's regenerated on every change via
the [`agents-md-sync`](.github/workflows/agents-md-sync.yml) CI workflow — **do not edit
`AGENTS.md` by hand**; the workflow fails the build if it drifts from its sources.

## Solution profile

Every agent reads **`solution-profile.yaml`** first (alongside `copilot-instructions.md`). It's
the single machine-readable source for the repo's operational facts: identity, documentation
root, backlog system + URL, tech stack, infrastructure, CI/CD, compliance, SLOs, and AI/Copilot
policy. Profile fields **override** an agent's defaults; safety / security defaults remain
non-negotiable. Copy [`solution-profile.yaml`](solution-profile.yaml) into a target repo's
`.github/` and fill in what applies.

## Conventions

### Hand-off block-name canon (do not change)
`dev-lead` parses these terminator blocks from worker output. Renaming any silently breaks the
pipeline: `IMPLEMENTATION COMPLETE`, `TESTS COMPLETE`, `INFRASTRUCTURE COMPLETE`,
`ARCHITECTURE DESIGN COMPLETE`, `REVIEW COMPLETE`, `TASKS PLANNED`.

### Vendored skills are read-only
The 26 vendored skills under `skills/` are unmodified copies from upstream. Do not edit them in
place — extend via a wrapper skill or contribute upstream and re-sync. See
[`skills/VENDORED.md`](skills/VENDORED.md).

### Working on the harness
See [`.github/copilot-instructions.md`](.github/copilot-instructions.md) for the full
development guide (flat-layout rule, model-tier convention, skill format, plugin manifests).

## License

[MIT](LICENSE). Vendored skills under `skills/` retain their upstream MIT license
(Copyright GitHub, Inc.) — see [`skills/VENDORED.md`](skills/VENDORED.md).

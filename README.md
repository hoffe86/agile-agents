# Agile Agents

The **Agentic Agile Harness** — packaged as installable GitHub Copilot CLI plugins.
It takes a prepared requirement and drives it to a reviewed change without a human
between stages: an **RPI pipeline** — **R**esearch → **P**lan → **I**mplement → **R**eview —
over 11 specialist agents (1 supervisor + 4 authors + 5 reviewers + a backlog-manager) plus
50 skills, with up-front concept + decision-record conformance, multi-lens review, and an eval/cost layer.

## Install

```shell
copilot plugin marketplace add hoffe86/agile-agents
copilot plugin install agile-agents-core@agile-agents-marketplace
```

The harness is technology-neutral. Add the companion plugins your project actually uses:

```shell
copilot plugin install agile-agents-dotnet@agile-agents-marketplace     # C# / .NET
copilot plugin install agile-agents-python@agile-agents-marketplace     # Python
copilot plugin install agile-agents-bicep@agile-agents-marketplace      # Bicep IaC
copilot plugin install agile-agents-terraform@agile-agents-marketplace  # Terraform IaC
copilot plugin install agile-agents-azure@agile-agents-marketplace     # Azure platform grounding
copilot plugin install agile-agents-ado@agile-agents-marketplace        # Azure DevOps Boards
copilot plugin install agile-agents-github@agile-agents-marketplace     # GitHub Issues
```

Agents route on **skill availability**, not on a hardcoded stack — an uninstalled companion
degrades to repo conventions rather than failing.

The `agile-agents-core` plugin ships `agents/` and the technology-neutral `skills/` (repo-scope +
user-scope). Per-project config (`solution-profile.yaml`) is a
one-file copy into your target repo's `.github/` (see [Solution profile](#solution-profile)).

## What you get

**11 agents** (`plugins/agile-agents-core/agents/`) — 1 supervisor + 4 authors + 5 reviewers + backlog-manager:

| Role | Agent | Purpose |
|------|-------|---------|
| Supervisor | `dev-lead` | Orchestrates the RPI pipeline (Research → Plan → Implement → Review) across architect, backlog-manager, coding, testing, and review with gates |
| Author | `architect` | Read-only/advisory: serves the Research phase — verifies the change fits the prepared concept (in the framework declared by `documentation.framework`) + any accepted decision records, cites them, reports decision gaps; never authors ADRs |
| Author | `coding` | Implements features/fixes (C# / Python) |
| Author | `testing` | Writes & runs tests (xUnit/NUnit/MSTest/TUnit, pytest) |
| Author | `infrastructure` | Bicep, Terraform, Helm/Kustomize, CI/CD pipelines |
| Backlog | `backlog-manager` | Creates / improves / reviews tracker work items (ADO, GitHub, Jira, Linear); in the Plan phase materialises `dev-lead`'s task breakdown as child work items linked to the parent story |
| Reviewer | `review` | Read-only orchestrator; merges all review lenses |
| Reviewer | `security-review` | OWASP, CWE, NIST SSDF, MS SDL, MCSB, OWASP LLM Top 10 |
| Reviewer | `architecture-review` | arc42, C4, WAF, AAC, microservices.io, DDD, ISO 25010 |
| Reviewer | `infrastructure-review` | WAF, AVM, CAF, CIS Azure, OIDC, SLSA |
| Reviewer | `test-review` | xUnit Test Patterns, Google Testing, Fowler test pyramid |

**Repo-scope skills** (`plugins/agile-agents-core/skills/`) — hand-written plus a set vendored from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills)
(intermixed flat). Includes `read-repo-context` — the foundation skill every agent loads first
— and `reviewer-read-only-rules`, the defence-in-depth contract every review agent loads. See
[`plugins/VENDORED.md`](plugins/VENDORED.md) for the vendored index across all plugins.

**Companion skills** across seven technology plugins — install only what your project uses:

| Plugin | Skills |
|---|---|
| `agile-agents-dotnet` | `csharp-implementation`, `csharp-testing`, `aspire`, `ef-core`, `dotnet-design-pattern-review` |
| `agile-agents-python` | `python-implementation`, `python-testing`, `pytest-coverage`, `ruff-recursive-fix` |
| `agile-agents-bicep` | `bicep-implementation`, `update-avm-modules-in-bicep` |
| `agile-agents-terraform` | `terraform-azure-implementation`, `terraform-azurerm-set-diff-analyzer`, `import-infrastructure-as-code` |
| `agile-agents-azure` | `azure-platform-grounding` |
| `agile-agents-ado` | `ado-work-items` |
| `agile-agents-github` | `github-issues` |

**Tracker MCP servers are named by you, not by this harness.** Tool grants are
agent-scoped — a skill cannot grant them — so `backlog-manager` ships grants for the
common server names (`github`, `ado`, `azure-devops`, …). If yours is registered under a
different name, add `'<your-server>/*'` to the `tools:` list in
`plugins/agile-agents-core/agents/backlog-manager.agent.md`. A server that isn't granted
is unreachable even while it's running; `backlog-manager` preflights for this and tells
you which of the two causes it hit.

**`agile-agents-azure` is grounding, not automation.** It carries the Azure substitutions core
deliberately does not know — CAF naming and tagging, AVM selection and pinning, secure-by-default
resource settings, the Well-Architected pillars as concrete review checks, and the MCSB / CIS Azure
control ids reviewers cite. All of it applies to a *diff or a design*, before anything is deployed,
which is what an agent reviewing a pull request actually needs.

For **live-subscription** work — scanning deployed resources, querying real spend, provisioning,
diagnostics — install Microsoft's own
[`microsoft/azure-skills`](https://github.com/microsoft/azure-skills) alongside it. It ships ~28
operational Azure skills plus the Azure MCP Server (200+ tools, 40+ services), maintained by the
team that owns the platform. This harness does not duplicate any of it:

```console
copilot plugin marketplace add microsoft/azure-skills
copilot plugin install azure@azure-skills
```

Without either plugin, the Azure lens degrades to the neutral cloud lens plus whatever
`microsoft-docs` returns — correct, but with no conventions to enforce and no live subscription
context.

**4 user-scope skills** (`plugins/agile-agents-core/user/skills/`) — bundled into the plugin and
available to every agent by description match. `working-style` and `trade-off-reporting` are named
explicitly by the agents; `code-review` and `cloud-native-patterns` are invoked on demand when
the task matches.

### MCP servers

Plugins ship their own MCP servers; every agent declares them, so an uninstalled companion
just means the tool isn't there.

| Server | Shipped by | Why |
|---|---|---|
| `context7` | `agile-agents-core` | Current, version-correct docs for whatever library the task touches — the cheapest defence against hallucinated APIs. |
| `microsoft-docs` | `agile-agents-core` | Microsoft Learn search / fetch / code samples. In core because the agents live in core and declare it; it also covers Azure, Bicep and ADO, not just .NET. |
| `playwright` | `agile-agents-core` | Interactive browser driving for `webapp-testing` — accessibility tree, console errors, failed requests, screenshots. Declared only by `testing`. Runs `--headless --isolated` (fresh profile per session, no state leaking between runs). |
| `azure-mcp` | *(user-installed — Microsoft's own [`azure-skills`](https://github.com/microsoft/azure-skills) plugin)* | Live Azure resource context: 200+ tools across 40+ services — resource inventory, Log Analytics / App Insights queries, quotas, pricing, deployment status. Declared by `architect`, `infrastructure` and `infrastructure-review`; the other agents review a diff and never query a subscription. Granted under three server-name aliases (`azure-mcp`, `azure-mcp-server`, `azure`) because the name varies by install method — unmatched grants are inert, so listing all three costs nothing and avoids a silent mismatch. |
| `microsoft/azure-devops-mcp` | *(user-installed)* | Work-item CRUD; used only by `backlog-manager`. |

### Tool access

Every agent gets the read/navigate set (`vscode, execute, read, search, web, todo`) plus the
MCP servers above. On top of that:

| Extra | Agents |
|---|---|
| `edit` | `architect`, `coding`, `testing`, `infrastructure`, `backlog-manager` |
| `agent` (delegation) | the above + `dev-lead`, `review` |
| `browser` | `testing` (E2E), `backlog-manager` (tracker web UI) |

**Reviewers never get `edit`.** That's the defence-in-depth half of
`reviewer-read-only-rules` — the contract is enforced in the prompt *and* by tool grant.

## How it works — the RPI pipeline

`dev-lead` is the supervisor. It drives a single, already-prepared user story through four
phases — **R**esearch → **P**lan → **I**mplement → **R**eview — delegating each phase to
specialist agents, gating their output, and reporting one Definition-of-Done verdict. The
concept (arc42, C4, or whatever `documentation.framework` declares) and any accepted decision
records are authored **up-front by humans**; the pipeline conforms to them and never writes
them — a missing decision is escalated, not invented. Projects without ADRs are supported.

```
Intake → Research → Plan → Create tasks → ⛔ HUMAN PLAN APPROVAL ⛔ → Implement → Test-Bar Gate → Review → Done
```

| Phase | What happens | Agents | Hand-off block |
|---|---|---|---|
| **Intake** | `dev-lead` captures the Definition of Done, out-of-scope, the **parent story id** (when creating tasks), confirms the `solution-profile.yaml`, and mints the run id. | `dev-lead` | — |
| **Research** | Read-only verification against the prepared concept + any accepted decision records: confirm the story is implementable, verify codebase / APIs / patterns, surface any decision gap. Lightweight (`dev-lead` reads) or delegated to `architect` when scope warrants a new boundary / dependency / trade-off. | `dev-lead`, `architect` | `ARCHITECTURE DESIGN COMPLETE` |
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
in `solution-profile.yaml` under `backlog.platform` + `backlog.url`. Task creation is gated by
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

**Layered evaluation.** This outcome eval is the top of a pyramid ([ADR 0008](docs/adr/0008-layered-evaluation-strategy.md)):
a free, deterministic **L0 trajectory eval** ([`eval/trajectory/`](eval/trajectory/README.md))
asserts each run's [`run-event-log`](plugins/agile-agents-core/skills/run-event-log/SKILL.md) stream conformed to the RPI
shape (dev-lead bookends, research→implement→test→**test-bar gate**→review ordering, reviewer
gate_checks, cost telemetry). It runs on every push/PR via the
[`Trajectory eval`](.github/workflows/trajectory-eval.yml) workflow — no credits, no model — and
catches process failures the outcome eval is blind to (e.g. a run that produces a plausible
artifact while its gates never fire). An L1 review-detection eval is planned.

> **Status:** `custom-eval` **invokes `dev-lead` for real** (`copilot --agent
> agile-agents-core:dev-lead --plugin-dir <repo>/plugins/agile-agents-core`) and **scores the result**: an LLM judge grades the
> produced workspace against the task's `acceptance.md` (`resolved`/`partial`/`failed`), with an
> optional deterministic per-task `score.ps1`/`score.sh` override for build/test-based checks.
> **SWE-bench task-prep** (dataset fetch + repo checkout) isn't wired yet. The workflow stays
> manual and non-gating. See [`eval/README.md`](eval/README.md#scoring).

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
platform + location + framework, backlog platform + URL, tech stack, infrastructure, CI/CD,
compliance, SLOs, and AI/Copilot
policy. Profile fields **override** an agent's defaults; safety / security defaults remain
non-negotiable. Copy [`solution-profile.yaml`](solution-profile.yaml) into a target repo's
`.github/` and fill in what applies.

## Conventions

### Hand-off block-name canon (do not change)
`dev-lead` parses these terminator blocks from worker output. Renaming any silently breaks the
pipeline: `IMPLEMENTATION COMPLETE`, `TESTS COMPLETE`, `INFRASTRUCTURE COMPLETE`,
`ARCHITECTURE DESIGN COMPLETE`, `REVIEW COMPLETE`, `TASKS PLANNED`.

### Vendored skills are read-only
The 19 vendored skills (spread across `plugins/agile-agents*/skills/`) are unmodified copies from upstream. Do not edit them in
place — extend via a wrapper skill or contribute upstream and re-sync. See
[`plugins/VENDORED.md`](plugins/VENDORED.md).

### Working on the harness
See [`.github/copilot-instructions.md`](.github/copilot-instructions.md) for the full
development guide (flat-layout rule, model-tier convention, skill format, plugin manifests).

## License

[MIT](LICENSE). Vendored skills under `plugins/agile-agents*/skills/` retain their upstream MIT license
(Copyright GitHub, Inc.) — see [`plugins/VENDORED.md`](plugins/VENDORED.md).


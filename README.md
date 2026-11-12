# Agile Agents

The **Agentic Agile Harness** — the `agile-agents-core` GitHub Copilot CLI plugin.
It takes a prepared requirement and drives it to a reviewed change without a human
between stages: an **RPI pipeline** — **R**esearch → **P**lan → **I**mplement → **R**eview —
over 15 specialist agents (1 supervisor + 4 authors + 7 reviewers, plus a backlog-manager, a bootstrapper and a capability-scout) plus
22 skills, with up-front concept + decision-record conformance, multi-lens review, and an eval/cost layer.

**Start here:** install `agile-agents-core`, then run **`bootstrapper`** — it profiles your repo,
writes the operational contract every agent reads, and proposes only the additional plugins your solution
needs. [Install →](#install)

## Install

```shell
copilot plugin marketplace add hoffe86/agile-agents
copilot plugin install agile-agents-core@agentic-universe
```

> **Compatibility:** Existing `agile-agents-marketplace` registrations and plugin
> installations are not automatically migrated to `agentic-universe`.

### Then run the bootstrapper — this is the first step

```shell
copilot --agent agile-agents-core:bootstrapper
```

…then tell it to set up the harness for the repo. (In an interactive session, selecting the
`bootstrapper` agent and asking it to "set up the harness for this repo" does the same thing.)

`bootstrapper` is the agent that configures the harness for your solution, and running it is how
you start. It:

1. **Reads your repo first**, then interviews you only for what no scan can tell it — lifecycle
   stage, test discipline, compliance scope, where documentation actually lives.
2. **Proposes and writes `.github/solution-profile.yaml` with approval**, preserving its
   schema and six required fields.
3. **Discovers existing scoped instructions, local skills, installed plugins and CI/check
   commands** before proposing gaps. Matches capabilities and applicability, not a catalog.
   Installs only selected plugins after explicit approval.
4. **Reports what is unavailable and the fallback**, distinguishing absent from
   ungranted, on-disk from available, and available from actually exercised.

Everything downstream depends on that profile: which skills load, which gates fire, which tracker
gets written to, what the cost envelope allows. `dev-lead` blocks at Stage 0 until its six
required fields are populated, so bootstrapping first saves a stopped run later.

Re-run it any time to repair or update the profile — it handles both.

### Optional model preferences — you configure them

`bootstrapper` can propose choices from your profile's advisory
`cost_envelope.model_tiers` map. You explicitly approve and configure preferred
models manually in the native `/subagents` UI; the harness never writes user/global
settings or derives per-call task models from that map. Existing explicit choices
and per-agent overrides win. A missing map leaves settings untouched, not forced
inheritance. If a model is unavailable, bootstrapper reports it for you to choose;
it never silently substitutes another approved model.

**Preference is not governance:** profile order is not a native ordered-fallback
guarantee, and preferred fallback may leave `ai_copilot.approved_models`. CI checks
static consistency only, not runtime authorization. Required-policy and Auto
interactions are unverified on CLI 1.0.98; no enforcement guarantee is claimed.
See the [manual setup procedure and version caveats](plugins/agile-agents-core/skills/cost-budget/references/tier-defaults.md#manual-native-setup).

### Choosing solution and personal guidance

The harness owns general engineering; your solution owns technical/tool/tracker
guidance and commands, locally or through selected external plugins. Match actual
skill descriptions and applicability, not historical names. Native instructions
retain their directory/`applyTo` scopes; do not flatten them into global guidance.
There is no required companion catalog, framework skill table or second registry.

Personal native instructions, skills and plugins are optional and user-selected,
with no required package/name. Absence is normal. Stricter personal consent is
valid; preferences cannot waive harness approvals/safety/reviewer boundaries or
supersede solution technical constraints. Report conflicts, not universal precedence.

The shared `agentic-universe` lists core 0.17.0 and the optional,
independently maintained
[`agentic-persona`](https://github.com/hoffe86/agentic-persona) plugin. Persona is
fetched directly from its own repository, not bundled into core or required by
the harness. No technical companion catalog is shipped.

After registering the marketplace above, install persona only if you want its
personal guidance. For an existing `agentic-universe` registration, refresh the
catalog first:

```shell
copilot plugin marketplace update agentic-universe
copilot plugin install agentic-persona@agentic-universe
```

Both plugins use this single marketplace; do not register a second catalog with
the same name. Persona's native user instructions require separate opt-in; see
its [setup documentation](https://github.com/hoffe86/agentic-persona#readme).

Removing a catalog listing does not uninstall existing copies. See
[customization ownership and rollback](docs/customization-ownership.md)
and the [documentation hub](docs/README.md).

Without matching optional depth, agents use repo conventions and authoritative
documentation and report the fallback. Ask **`capability-scout`**
(`copilot --agent agile-agents-core:capability-scout`) to actively discover trusted
skills, plugins or instruction improvements, including better replacements for
covered needs. Its proposal records provenance/trust/license, overlap/conflicts,
harness/solution/user destination, expected benefit and before/after verification.
It never adopts, installs or edits instructions; a human approves those changes.

All 15 agent definitions use the wildcard tool grant; native `skill` invocation
and selective instruction loading still depend on runtime behavior. Static
checks do not establish role-wide live loading or automatic selective
instruction injection. Full RPI evaluation is currently blocked at approval
transport.

The `agile-agents-core` plugin ships `agents/` and the technology-neutral `skills/`.

## What you get

**15 agents** (`plugins/agile-agents-core/agents/`) — 1 supervisor + 4 authors + 7 reviewers + backlog-manager + bootstrapper + capability-scout:

| Role | Agent | Purpose |
|------|-------|---------|
| Supervisor | `dev-lead` | Orchestrates the RPI pipeline (Research → Plan → Implement → Review); after approval may author application/IaC tasks and tests directly or delegate them. Data-science analysis remains delegated to `data-scientist`. |
| Author | `architect` | Read-only/advisory: serves the Research phase — verifies the change fits the prepared concept (in the framework declared by `documentation.framework`) + any accepted decision records, cites them, reports decision gaps; never authors ADRs |
| Author | `coding` | Implements features/fixes **and covers them with tests** using the solution's language/framework — one engineer's job, one hand-off |
| Author | `infrastructure` | Bicep, Terraform, Helm/Kustomize, CI/CD pipelines — and their IaC tests |
| Author | `data-scientist` | Analysis, experiments, models and their evaluation — two rubrics (classical ML and AI/LLM). Owns the model and its evidence; `coding` owns the app that serves it |
| Backlog | `backlog-manager` | Creates / improves / reviews tracker work items (ADO, GitHub, Jira, Linear); in the Plan phase materialises `dev-lead`'s task breakdown as child work items linked to the parent story |
| Bootstrap | `bootstrapper` | Discovers existing guidance and commands, interviews for missing facts, writes the approved profile, installs only selected approved plugins, and reports remaining gaps/fallbacks |
| Improvement | `capability-scout` | Proposes trusted skills, plugins and instructions, including better replacements for covered needs, with ownership, evidence and before/after verification. Read-only — never adopts |
| Reviewer | `review-lead` | Read-only orchestrator: triages which lenses the diff warrants, dispatches them in parallel, merges into one ranked report with one verdict. Performs no lens itself |
| Reviewer | `code-reviewer` | General code quality — correctness, line-level design, readability, standards, regressions, cloud-native anti-patterns, docs currency |
| Reviewer | `security-reviewer` | OWASP, CWE, NIST SSDF, MS SDL, MCSB, OWASP LLM Top 10 |
| Reviewer | `architecture-reviewer` | arc42, C4, WAF, AAC, microservices.io, DDD, ISO 25010 |
| Reviewer | `infrastructure-reviewer` | WAF, AVM, CAF, CIS Azure, OIDC, SLSA |
| Reviewer | `test-reviewer` | xUnit Test Patterns, Google Testing, Fowler test pyramid |
| Reviewer | `data-reviewer` | Statistical validity — leakage, baselines, metric choice, uncertainty, cohort fairness, reproducibility, dataset provenance |

**Repo-scope skills** (`plugins/agile-agents-core/skills/`) — hand-written plus a set vendored from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills)
(intermixed flat). Includes `read-repo-context` — the foundation skill every agent loads first
— and `reviewer-read-only-rules`, the defence-in-depth contract every review agent loads. See
[`plugins/VENDORED.md`](plugins/VENDORED.md) for the vendored index across all plugins.

The generated [skill inventory](AGENTS.md) lists the current distribution.
Solution-local guidance can use arbitrary names; no companion is required.

### Tool access

All 15 agent definitions use `tools: ["*"]`. This exposes tools made available
through the runtime, workspace, or global configuration; it does not register an
absent MCP server, grant authorization to an external service, or bypass local
or host restrictions. Tool availability and service authorization remain owned by
the configured runtime and service.

The core plugin declares these MCP servers:

| Server | Shipped by | Why |
|---|---|---|
| `context7` | `agile-agents-core` | Current, version-correct docs for whatever library the task touches — the cheapest defence against hallucinated APIs. |
| `microsoft-docs` | `agile-agents-core` | Microsoft Learn search / fetch / code samples. In core because the agents live in core and declare it; it also covers Azure, Bicep and ADO, not just .NET. |
| `playwright` | `agile-agents-core` | Interactive browser diagnosis and rendered documentation. Runs `--headless --isolated`; profile isolation is not a network/security sandbox. |

Other MCP servers, such as a tracker or Azure server, must be made available by
the consuming environment. Their availability does not change role ownership:
tracker operations belong to `backlog-manager`, and Azure resource work belongs
to the roles assigned that task.

Reviewers and `capability-scout` remain effect-based read-only / proposal-only
roles despite the open tool grants; the grants do not technically deny editing
or other write-capable tools. Reviewers must not edit files, mutate external
state, submit forms, authenticate through the console, or run unsafe browser
code. `capability-scout` proposes changes but does not adopt, install, or edit
them. `reviewer-read-only-rules` is authoritative: a tool's effect, not its
interface, determines whether an action is a write.

## How it works — the RPI pipeline

`dev-lead` is the supervisor. It drives a single, already-prepared user story through four
phases — **R**esearch → **P**lan → **I**mplement → **R**eview — delegating as appropriate,
gating the work, and reporting one Definition-of-Done verdict. After plan approval, it may
choose to author an approved application/IaC task and its tests directly or
delegate to the corresponding specialist. Data-science analysis remains
delegated to `data-scientist`, as allowed by the [approved ADR 0009 amendment](docs/adr/0009-merge-coding-and-testing-agents.md).
The concept (arc42, C4, or whatever
`documentation.framework` declares) and any accepted decision records are
authored **up-front by humans**; the pipeline conforms to them and never writes
them — a missing decision is escalated, not invented. Projects without ADRs are
supported.

Intake → Research → Plan → tracker tasks → **human approval** → implementation
and tests → deterministic gates → independent review → Done.
The [supervisor](plugins/agile-agents-core/agents/dev-lead.agent.md) defines retry
limits: at most three deterministic corrective retries, and at most three
non-Block review rounds. A ❌ Block halts rather than entering that loop.

| Phase | What happens | Agents | Hand-off block |
|---|---|---|---|
| **Bootstrap** *(once, before the first run)* | `bootstrapper` discovers existing guidance/commands, writes the approved profile and installs only selected approved plugins. Re-run to repair. `dev-lead` delegates if the profile is missing or incomplete. | `bootstrapper` | `BOOTSTRAP COMPLETE` |
| **Intake** | `dev-lead` captures the Definition of Done, out-of-scope, the **parent story id** (when creating tasks), confirms the `solution-profile.yaml`, and mints the run id. The requirement can arrive as text, a tracker item, a requirements file, or a **planning-mode `plan.md`** — for the last, criteria are derived from the plan and confirmed with you once. | `dev-lead` | — |
| **Research** | Read-only verification against the prepared concept + any accepted decision records: confirm the story is implementable, verify codebase / APIs / patterns, surface any decision gap. Lightweight (`dev-lead` reads) or delegated to `architect` when scope warrants a new boundary / dependency / trade-off. | `dev-lead`, `architect` | `ARCHITECTURE DESIGN COMPLETE` |
| **Plan** | Decompose the story into meaningful, independently-implementable **tasks**, each with its own acceptance criteria + a short approach note. When a `plan.md` supplied the decomposition, it is **adopted and reconciled** — every step carried, merged, or dropped with a reason — never silently re-derived. | `dev-lead` | — |
| **Create tasks** | `backlog-manager` creates one child work item per task, **linked to the parent story** (provisional, tagged `pending-approval`), records the overall approach as a comment on the parent, and returns the task list. The tracker is the source of truth; local handover files are an ephemeral, gitignored cache. Gated by `backlog.create_tasks`. | `backlog-manager` | `TASKS PLANNED` |
| **⛔ Plan approval** | The **only mandatory approval gate** — it fires **after** the tasks exist so the human reviews concrete, linked work items. ("Only" counts approvals: intake may still ask about an ambiguity, or to confirm criteria derived from a `plan.md`.) Approve → tags removed, autonomous run begins; Adjust → tasks revised; Cancel → provisional tasks cleaned up. | human | — |
| **Implement** | For each approved application/IaC task, `dev-lead` chooses direct authorship (including tests) or delegates to `coding` / `infrastructure`. Data-science analysis stays delegated to `data-scientist`. Approval still precedes work; the deterministic test bar and independent review remain mandatory. | `dev-lead`, `coding`, `infrastructure`, `data-scientist` | None for direct `dev-lead` authorship; specialist hand-off blocks for delegated work |
| **Test-Bar Gate** | Deterministic lint → typecheck → unit-test → smoke gate over the combined diff, before reviewers spend tokens; loops back to the author on fail (max 3 retries). | `dev-lead` (skill: `test-bar-gate`) | — |
| **Review** | Multi-lens review (quality / security / architecture / infra / test / data) merged into one verdict, validated against the research findings and the planned acceptance criteria. | `review-lead` (+ `code-reviewer`, `security-reviewer`, `architecture-reviewer`, `infrastructure-reviewer`, `test-reviewer`, `data-reviewer`) | `REVIEW COMPLETE` |
| **Done** | `dev-lead` reconciles evidence, relays trade-offs and uses the completion reference for approved PR/release artifacts. | `dev-lead` | — |

After the plan is approved, the run is **autonomous** — it stops only on a defined stop
condition (ambiguity, exhausted gate retries, scope change, destructive action,
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

**DeepEval is the sole active pipeline scorer**
([ADR 0015](docs/adr/0015-deepeval-for-pipeline-evaluation.md)). It measures coverage
of expected skill identities in existing Copilot JSONL traces using the pinned
offline metric. It does not launch agents, call models or execute generated artifacts.
Recorded invocation is not successful skill use, task acceptance or L2 outcome credit.

| Evaluation responsibility | Evidence |
|---|---|
| [DeepEval pipeline scoring](eval/deepeval/README.md) | Recorded expected-skill coverage; setup/schema errors remain distinct from measured failures |
| [Deterministic L0 trajectory checks](eval/pipeline/trajectory/README.md) | RPI ordering, gates and cost telemetry in harness event logs ([ADR 0008](docs/adr/0008-layered-evaluation-strategy.md)) |
| [Waza skill evaluation](eval/skills/README.md) | Individual-skill routing, invocation and efficacy ([ADR 0014](docs/adr/0014-skill-evaluation-with-waza.md)) |

Use `eval/deepeval/report_skill_usage.py` with `--score`, repeated
`--expect-skill` values and a local `--output` JSON destination.
[Installation and command reference](eval/deepeval/README.md) are separate from
the [evaluation overview](eval/README.md).
Shared implementation remains in `eval/python/agile_eval`, without shadowing
third-party `deepeval`.

The ten [custom benchmark tasks](eval/pipeline/custom-eval/README.md) run live:
dev-lead is driven through the Copilot CLI across a human plan gate, and DeepEval
scores the plan gate, delegation and per-agent skill invocation, with an optional
model judge for acceptance. Runs are not OS-sandboxed yet
([#22](https://github.com/hoffe86/agile-agents/issues/22)). The 25-instance
[SWE-bench manifest](eval/pipeline/swe-bench-subset/README.md) and
[historical baselines](eval/baselines.md) remain data and historical evidence.

### `metadata.model_tier` frontmatter convention
Each Copilot agent records an **advisory preference**, not a model selector
([ADR 0007](docs/adr/0007-model-tier-convention.md)):

```yaml
metadata:
  model_tier: heavy
```

Native fields such as `model`, `tools`, and `description` stay at the top level.
Runtime-native settings govern actual model selection; no tier resolver or automatic
`ai_copilot.approved_models` enforcement exists here. The optional
`cost_envelope.model_tiers` profile map records preferences only: no runtime code
consumes it. Use the [consumer-owned setup](#optional-model-preferences--you-configure-them)
above; shipped agents have no `model` / `models` pins. This annotation convention is
Copilot-specific, not a cross-harness contract.
Tier values require ordered nonempty lists of model IDs.
The existing frontmatter checker validates the root profile and shipped template:
only `heavy` / `mid` / `light`, no duplicates, and each listed model must be in
`ai_copilot.approved_models`. This is static consistency checking, not runtime
authorization, selection, or fallback. Consumer fixtures are not scanned as root profiles.
The shipped template stays empty and generic; this repository's seven approved IDs
and ordered preferences belong only in `.github/solution-profile.yaml`.
The approved assignments reflect `dev-lead`'s deep-reasoning responsibilities for
planning/decomposition, acceptance coverage, risk sequencing, and gate judgement;
the other 14 assignments are unchanged:

| Agent | Tier |
|---|---|
| `dev-lead` | heavy |
| `coding`, `infrastructure`, `backlog-manager`, `bootstrapper` | mid |
| `architect`, `capability-scout`, `data-scientist`, `review-lead`, `code-reviewer`, `architecture-reviewer`, `security-reviewer`, `infrastructure-reviewer`, `test-reviewer`, `data-reviewer` | heavy |

The roster has 0 light, 4 mid, and 11 heavy agents; `light` remains a supported tier.

**Dogfood test bar.** At repository root, activate a Python environment with
`eval/deepeval/requirements.lock.txt` hash-installed
([setup and supported Python versions](eval/deepeval/README.md#install-and-verify)) and put `pwsh` on `PATH`. The profile's
`lint.command` and `unit_test.command` call `python scripts/run-repo-checks.py lint`
and `python scripts/run-repo-checks.py unit`. The helper stops on any failed command
or missing prerequisite. Unit checks use unittest for script, pipeline-workflow,
and trajectory tests, and pytest only for custom-eval/deepeval; running all paths
through pytest incorrectly collects trajectory helper functions as tests.
There is no configured static type checker, application smoke command, or deployment.
Run the actual profile integration with either:

```text
pwsh -NoProfile -File plugins/agile-agents-core/skills/test-bar-gate/scripts/run-gate.ps1 -ProfilePath .github/solution-profile.yaml -SmokeStatus not_applicable -SmokeDetail "Harness scripts and documentation; no application entry point"
bash plugins/agile-agents-core/skills/test-bar-gate/scripts/run-gate.sh --profile .github/solution-profile.yaml --smoke-status not_applicable --smoke-detail "Harness scripts and documentation; no application entry point"
```

The PowerShell gate requires `powershell-yaml` (7.2+ for smoke signal cleanup); the Bash gate requires mikefarah
`yq` v4. These are existing gate prerequisites, not optional skips. Checks are
offline: this does not enable live evaluation or change budget caps.

**Explicit gate commands.** Language palettes and tool aliases are not supported.
Set each enabled `quality_gates.test_bar.<check>.command` from existing solution
CI/scripts, with provenance and prerequisites in solution guidance. Empty enabled
commands are configuration gaps (exit 2), not unsupported-stack passes.
Compose polyglot checks in solution-owned scripts; `stacks` is rejected.
Disabled checks are visible skips.
Smoke still uses `testing.smoke.command`, `url`, `timeout_s`: missing setup or
`undetermined` exits 2 and blocks verified Done. Only an inspected non-runnable
project uses the evidenced `not_applicable` flags above. See
[gate contract](plugins/agile-agents-core/skills/test-bar-gate/SKILL.md).
Only declared command fields are supported. Scalar model-tier values are
rejected; there are no aliases. The implicit profile
path is `.github/solution-profile.yaml`; other locations need an explicit path.
PowerShell smoke's explicit Unix signal cleanup requires 7.2+; older
hosts report a configuration gap before starting a process.

`scripts/check-skill-frontmatter.py` requires string-to-string agent metadata, restricts
the tier to `light` / `mid` / `heavy`, rejects legacy top-level tiers and nested native
fields, and checks the core inventory and assignments. It does **not** apply the agent
string-map schema to `SKILL.md`: skill scope is now the nonempty string
`metadata.applies_to`. Missing/non-mapping metadata, invalid scope, legacy top-level
scope, duplicate YAML keys, and nested native skill fields fail validation. Unknown
inherited metadata is preserved, including upstream `acquire-codebase-knowledge`'s
version string and enhancements list; this is deliberately not full AgentSkills
string-map conformance. Vendored drift ignores only this annotation within frontmatter
(and a wrapper introduced solely for it), never body text or upstream scope collisions.
Its inline self-test fixtures cover invalid shapes/types and misplaced fields.
`SkillMetadataTests` and `VendoredNormalizationTests` cover scope validation and lossless
comparison; `AgentMetadataTests` covers inventory
mutations, native-model independence, and both generators' description handling:

```shell
python scripts/check-skill-frontmatter.py --self-test
python scripts/check-skill-frontmatter.py
python -m unittest scripts.tests.test_runtime_contracts.AgentMetadataTests -v
```

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
non-negotiable.

**`bootstrapper` writes it for you** — that is the point of running it first. It discovers what
the repo already states, asks only for the rest, and leaves a field empty rather than guessing,
because a fabricated `test_discipline` or `location` misdirects every downstream agent silently.

To fill it in by hand instead, copy the template from
[`plugins/agile-agents-core/skills/solution-profile-interview/references/solution-profile.template.yaml`](plugins/agile-agents-core/skills/solution-profile-interview/references/solution-profile.template.yaml)
into your repo's `.github/`. Six fields are required before `dev-lead` will start:
`identity.project_name`, `identity.lifecycle_stage`, `documentation.location`,
`backlog.platform`, `tech_stack.primary_languages`, `tech_stack.test_discipline`.

## Conventions

### Hand-off block-name canon (do not change)
`dev-lead` parses these terminator blocks from worker output. Renaming any silently breaks the
pipeline: `IMPLEMENTATION COMPLETE`, `INFRASTRUCTURE COMPLETE`,
`ARCHITECTURE DESIGN COMPLETE`, `REVIEW COMPLETE`, `TASKS PLANNED`, `BOOTSTRAP COMPLETE`.
`IMPLEMENTATION COMPLETE` includes test evidence; there is no separate testing hand-off.

### Vendored skills are read-only
`acquire-codebase-knowledge` is the sole vendored skill, retained for explicit
onboarding. Do not edit its upstream body; contribute upstream and re-sync. See
[`plugins/VENDORED.md`](plugins/VENDORED.md).

### Working on the harness
See [`.github/copilot-instructions.md`](.github/copilot-instructions.md) for the full
development guide (flat-layout rule, model-tier convention, skill format, plugin manifests).

## License

[MIT](LICENSE). Vendored skills under `plugins/agile-agents*/skills/` retain their upstream MIT license
(Copyright GitHub, Inc.) — see [`plugins/VENDORED.md`](plugins/VENDORED.md).

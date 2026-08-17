# Copilot Instructions — Agile Agents

## Repository purpose

This repo implements the **Agentic Agile Harness** — the orchestration
layer, specialist agent roster, skills, gates, and operational profile that let an
agentic CLI take a prepared requirement and drive it to a reviewed change without a
human in the loop between stages. The harness is what this repo builds; the code it
writes lives in *other* repos.

It ships as a GitHub Copilot CLI **marketplace of eight plugins** - `agile-agents-core`
(agents + technology-neutral skills) plus seven `agile-agents-<technology>` companions. This
repo is both the source you edit and the marketplace others install from.

Harness, concretely: `dev-lead` (supervisor) runs the RPI pipeline over a roster of
specialist agents, each constrained by a declared tool grant and a sentinel hand-off
block; `skills/` supply the procedural knowledge agents load on demand;
`solution-profile.yaml` is the per-project operational contract (stack, gates, budget,
autonomy); `eval/` measures whether the harness actually works. Changes here change
*agent behaviour at runtime* — treat every edit as a behaviour change, not a doc edit.

### Technology scope

The **harness** — orchestration, gates, hand-offs, review lenses, event log, cost
envelope — is technology-agnostic and must stay that way. The bundled **skill library**
is deliberately not: it targets **Azure + .NET / Python + Bicep / Terraform**, because
that is what the harness is used to deliver.

Concretely:

- **In scope** — deepening the Azure / .NET / Python / Bicep / Terraform skills; any
  technology-agnostic engineering technique.
- **Out of scope** — AWS / GCP equivalents, a skill per JavaScript or Python framework,
  language skills for ecosystems nobody here ships. Those belong in a downstream fork or
  a separate plugin, not in this bundle.
- **Never technology-coupled** — the agents themselves. An agent may *route to* a
  language, cloud, or IaC skill; it may not assume one. Routing branches key on **skill
  availability**, not on the technology name, so a renamed, removed, or separately-shipped
  skill degrades to "no deep skill" instead of a dangling instruction. A worker with no
  matching skill falls back to the repo's own conventions and says so in its hand-off.
- **Azure is a default, not a requirement.** The suite installs and runs without Azure.
  Azure-specific guidance (AVM, CAF, WAF, CIS Azure, MCSB, `azure-mcp/*` tooling) is gated
  on `solution-profile.yaml: infrastructure.cloud`; on any other cloud, on-prem, or hybrid
  those references are not applicable and must not be raised as findings. The cloud-neutral
  lens — secrets handling, least-privilege, encryption, backup, logging, pipeline
  supply-chain hardening — always applies.

If a task needs an ecosystem with no skill, that is a gap to report, not a reason to hard-code
the tooling into an agent.

The suite is consumed **as a Copilot CLI plugin** — `copilot plugin marketplace add
hoffe86/agile-agents` then `copilot plugin install agile-agents-core@agile-agents-marketplace`, plus whichever
`agile-agents-<technology>` companion plugins the project needs. The CLI loads `agents/`,
and `skills/` directly from each plugin (see
`plugins/<name>/.github/plugin/plugin.json`). Per-project config
(`solution-profile.yaml`) is copied into the target repo's `.github/`.

## Repository structure

```
agent/                               Marketplace root
├── .github/
│   ├── copilot-instructions.md      This file
│   ├── solution-profile.yaml        This repo's own profile - byte-identical to the
│   │                                template it ships (see below)
│   ├── plugin/marketplace.json      Marketplace listing (agile-agents-marketplace,
│   │                                pluginRoot ./plugins)
│   └── workflows/                   4 workflows -> CI checks audit-references,
│                                    check-agents-md-in-sync, trajectory,
│                                    plugin-versions
├── plugins/                         One folder per plugin
│   ├── VENDORED.md                  Index of vendored skills across all plugins
│   ├── agile-agents-core/           The autonomous-coding agent harness
│   │   ├── .github/plugin/plugin.json   Plugin manifest (name: agile-agents-core)
│   │   ├── agents/                  15 *.agent.md (1 supervisor + 4 authors
│   │   │                            + 7 reviewers + backlog-manager + bootstrapper
│   │   │                            + capability-scout)
│   │   ├── skills/                  41 repo-scope skills, incl.
│   │   │                            solution-profile-interview/references/
│   │   │                            solution-profile.template.yaml
│   ├── agile-agents-dotnet/         6 skills — C# / .NET
│   ├── agile-agents-python/         5 skills — Python
│   ├── agile-agents-bicep/          3 skills — Bicep IaC
│   ├── agile-agents-terraform/      3 skills — Terraform IaC
│   ├── agile-agents-azure/          1 skill  — Azure platform grounding (CAF / AVM / WAF)
│   ├── agile-agents-ado/            1 skill  — Azure DevOps Boards tracker mechanics
│   └── agile-agents-github/         1 skill  — GitHub Issues tracker mechanics
├── scripts/                         generate-agents-md.{ps1,sh}, audit-references.ps1,
│                                    check-plugin-versions.ps1
├── eval/                            swe-bench-subset + custom-eval + trajectory + baselines.md
├── docs/
│   ├── adr/                         Architecture decision records (0001–0008)
│   ├── research/                    Whitepaper + spikes
│   └── AGENTS-MD-MAPPING.md         Folder→agent mapping for the generator
├── AGENTS.md                        Generated — do not hand-edit
└── README.md
```

### Multi-plugin layout
This repo is a **marketplace**, not a single plugin. Each plugin is a self-contained folder
under `plugins/<name>/` carrying its own `.github/plugin/plugin.json` whose `agents` /
`skills` paths are **relative to the plugin root**. The repo-level
`.github/plugin/marketplace.json` declares `"metadata": { "pluginRoot": "./plugins" }` and
one `plugins[]` entry per plugin with `"source": "<name>"`. To add a plugin: create
`plugins/<name>/` with a manifest, then add its marketplace entry. Do not put agents or
skills at the repo root.

**What belongs where.** `agile-agents-core` holds the agents and every **technology-neutral** skill.
Anything tied to one language, IaC tool, or tracker ships in a `agile-agents-<technology>`
companion plugin so a project installs only what it uses. Agents route on **skill
availability**, never on a hardcoded technology list — an uninstalled companion must degrade
to repo conventions, not fail. Split a new companion out only when the technology has a
genuinely exclusive audience (a team picks Bicep *xor* Terraform, ADO *xor* GitHub Issues);
don't split things everyone installs anyway.

**Sharing between plugins.** There is no cross-plugin reference — a sub-agent named in
another plugin's `agents:` list will not resolve. Shared artifacts are instead **listed in
every manifest that needs them** (hve-core ships `agents/hve-core/subagents/` in three
plugins). Nothing is currently shared here: each skill lives in exactly one plugin.

### Flat-layout rule
Manifest paths are **not** recursive — `"agents": ["agents/"]` picks up `agents/*.agent.md`
and nothing deeper. Nesting is therefore possible but only if every subfolder gets its own
manifest entry (hve-core does this: `agents/hve-core/`, `agents/hve-core/subagents/`).
**This repo stays flat** — no plugin holds enough artifacts to need the extra level, and a
flat tree can't silently drop an artifact by forgetting a manifest line. Every `*.agent.md`
and every `skills/<name>/` subfolder sits directly under its parent; there are no `coding/`
or `backlog/` category folders.

### Tool grants (four rules, each learned the hard way)
An agent's `tools:` frontmatter is a **filter, not a hint** — a server that is running and
configured is still unreachable if it is not granted. Getting this wrong is silent in both
directions, which is why it has produced a bug in three separate PRs.

1. **A grant must name the server exactly as it is registered** — copied verbatim from
   `mcp-config.json`, not guessed. A registered name may itself contain a slash
   (`microsoft/azure-devops-mcp`, `microsoftdocs/mcp`), so `audit-references.ps1` matches
   the **whole grant** first and only then falls back to the first segment. An earlier probe
   concluded that a grant may carry at most one slash and an arity check was added on that
   basis; it was wrong and had to be reverted — the probe registered the server as
   `probesrv` and then tested the grant `vendor/probesrv/*`, which cannot separate "the
   second slash is invalid" from "that is not this server's name".
2. **Grants live in agent frontmatter. A skill cannot grant anything.** Skill-level
   `allowed-tools:` is inert — measured on CLI 1.0.79, same skill and prompt, only the
   agent's `tools:` changed the outcome. It is inert for confirmation prompts too.
3. **An unmatched grant is free.** It neither errors nor warns, so covering every alias a
   server is registered under (`ado/*`, `azure-devops/*`, `azure-devops-mcp/*`) is the right
   move in a harness whose users each keep their own `mcp-config.json`.
4. **Rule 3 is also why the failure is invisible.** From inside a session, "not granted" and
   "not installed" look identical. Any agent that depends on an external server must
   preflight and report **both** causes with the fix for each — never just "unavailable".

### Write-permission policy (keep every agent consistent with this)
Two gates, one hard boundary — keep every agent consistent with this:
- **Branch / commit / push** are **ungated** — agents do their own git. The guard is branch
  discipline: work lands on a feature branch, never on the default branch.
- **Opening a pull request** is **approval-gated**: the user approves it explicitly, per run, and
  approval is never inferred from silence or from the Stage 4 plan approval.
- **Deployments to non-production** go through the project's own pipeline and are **profile-gated**
  on `infrastructure.deploy_verify: dev`. Non-production means any `environment_chain` entry except
  the last and except any entry containing `prod`.
- **Completing / merging / closing a PR is human-only, always** — as are force-pushing, rewriting
  shared history, deleting shared branches, and production deploys. No profile key unlocks these.

Reviewers remain read-only regardless (`reviewer-read-only-rules`). State a refusal as a
**boundary or a pending approval**, never as a missing tool: when the ban was merely absent,
agents diagnosed it as a broken MCP server and reported a tooling failure.

The PR command derives from **`identity.repo_url`**, never from `backlog.platform` — code
host and board host are independent, and a project may keep code on GitHub with work items
in Azure Boards.

### Agent naming convention (`-reviewer` is an actor, `-review` is a process)
Read-only review agents end in **`-reviewer`**; the skills that carry review *knowledge*
keep **`-review`**. So `code-reviewer` (agent) loads nothing from `code-review` (skill), and
`security-reviewer` (agent) may cite `security-review` (vendored skill) without either name
being ambiguous. The orchestrator is **`review-lead`**, mirroring `dev-lead` — it supervises
reviewers rather than being one, so it does not take the lens suffix.

**Never give an agent and a skill the same name.** `audit-references.ps1` skips backticked
agent names so that "delegate to `test-reviewer`" is not read as a skill reference — which
means a shared name can never be validated, and deleting the same-named skill leaves the
audit green. That was live for `code-review` and `security-review` until the rename; no
purely name-based rule can distinguish "agent named in prose" from "skill that vanished".

### Hand-off block-name canon (do not change)
Worker agents emit a recognisable terminator block on completion — `dev-lead` parses these.
Renaming any silently breaks the pipeline:
- `IMPLEMENTATION COMPLETE` (coding — production code **and** the tests covering it)
- `ANALYSIS COMPLETE` (data-scientist — an answer plus its evidence; ⚠️ inconclusive and ❌ not-supported are **completed** outcomes, not failures)
- `INFRASTRUCTURE COMPLETE` (infrastructure)
- `ARCHITECTURE DESIGN COMPLETE` (architect)
- `REVIEW COMPLETE` (review-lead — the specialist reviewers report into it, they do not emit it)
- `TASKS PLANNED` (backlog-manager — the Plan-phase task-creation hand-off)
- `BOOTSTRAP COMPLETE` (bootstrapper — the one-off profile + plugin bootstrap)

`TESTS COMPLETE` was retired when `coding` and `testing` merged (ADR 0009). Do not
re-introduce it: `IMPLEMENTATION COMPLETE` now carries the test fields, and a second block
from the same agent would give `dev-lead` two gates over one diff.

### RPI pipeline + tasks-in-tracker
`dev-lead` orchestrates the **RPI pattern** — **Research → Plan → Implement → Review**:
- **Research** — read-only verification against the *already-prepared* concept (arc42 / C4)
  and accepted ADRs; delegates to `architect` when scope warrants. The pipeline conforms to
  those up-front decisions and never authors them; a missing decision is escalated to humans.
- **Plan** — decompose the requirement into independently-implementable tasks (acceptance criteria
  + approach note). When `backlog.create_tasks` is true, `backlog-manager` creates them as
  **child work items linked to the parent work item** (provisional, tagged `pending-approval`)
  and emits `TASKS PLANNED`. The **mandatory human plan-approval gate fires after task
  creation**. Tasks live in the tracker, not as files; in-run hand-off state is the
  orchestrator's own task list, and the tracker wins on any conflict.
- **Implement / Review** — `coding` (application code *and* its tests) + `infrastructure` (IaC
  *and* its tests), then the deterministic test bar, then multi-lens review. Stage 9
  verifies the delivered change covers the *requirement*, not merely that every task passed.

**One agent writes the code and its tests** (ADR 0009) — the split cost a hand-off round
without buying independence, since the independent judgement is the reviewers' and they are
different agents by design. The guard that replaces the split is explicit: an author may fix
production code to pass a test, but never weaken a test to pass production code, and every
modified existing test is justified in the `Existing tests modified` hand-off field, which
`dev-lead` gates on and `test-reviewer` adjudicates.

**The reviewers went the other way, deliberately** (ADR 0010). `review-lead` performs **no lens
itself** — it triages, dispatches five read-only specialists in parallel (`code-reviewer`,
`security-reviewer`, `test-reviewer`, `architecture-reviewer`, `infrastructure-reviewer`), and merges.
The merge logic that applied to `coding`+`testing` does not transfer here: reviewers never
hand off to each other, so the split costs no round, and independence is the product rather
than a side-effect. Do not "consolidate" a lens into the orchestrator to save a dispatch —
that is exactly the arrangement ADR 0010 undid, where the merge always completed and the
line-by-line reading silently degraded on large diffs.

Tasks are dispatched **one at a time**, even when the dependency graph says they are
independent. Sub-agents share one working tree, so concurrent writers interleave edits and
no gate can attribute a failure to a task — independent in the graph is not disjoint in the
diff. (`review-lead` fans out in parallel only because all six lenses are read-only.) The
upgrade path is a git worktree per task plus a merge step; do not "fix" this by spawning
concurrent writers.

Acceptance criteria are captured **verbatim at intake** and verified at Stage 9 against
**evidence** — a test name or a review finding. Every gate used to compare against its
predecessor and none against the source, which looks closed-loop but lets a criterion lost
at decomposition pass silently.

Say **requirement**, not *story* or *user story*. A requirement can arrive as a tracker item
or as a markdown file, and the pipeline must not assume a tracker exists.

### Tracker status lifecycle (neutral names only)
`dev-lead` mirrors each task onto its tracker item using exactly four neutral names —
`in_progress`, `implemented`, `blocked`, `done` — and is **forbidden from naming a
tracker's own state**. `backlog-manager` resolves them: `backlog.task_states` from the
profile, else the states the item actually accepts, else post a comment and say so.

`implemented` (code-complete, unverified) is deliberately not `done` (delivered, verified
at Stage 9). Where a tracker cannot express `implemented`, the item **stays where it is
and gets a comment** — it must never fall back to the terminal state, because closing on
code-completeness claims a verification that has not happened and no later transition
undoes it once the team has watched the item leave the board.

A failed status write **warns and continues** (observability), unlike a failed task
*creation*, which halts the run (without work items there is no approved plan).

### Cost and usage telemetry (do not re-introduce self-reporting)
**No agent can observe its own token consumption** — there is no tool, env var, or
transcript field that exposes it. Any token or USD figure an agent writes is invented.
This was a real bug: `emit-event` once accepted `-TokensIn`/`-CostUsd`, the docs marked
them *Recommended*, nothing ever filled them, and the cost gate reported `$0.00` and
**exited 0** from the day it was written until a real run surfaced it.

So: the event schema carries **no** token or cost fields, and
`skills/cost-budget/scripts/collect-usage.py` reads the CLI's own usage store instead,
attributing usage to phases by timestamp window.

Consequences worth preserving:
- **Only `dev-lead` emits events.** Because attribution is by time window, workers need no
  instrumentation — only the orchestrator knows the phase structure.
- **Every `phase_start` needs a matching `phase_complete`**, or that phase's usage falls
  into `unattributed`. The `trajectory` CI check enforces both this and the absence of
  self-reported cost fields.
- **Gate on AIU or tokens, never USD.** Cache reads bill at a tenth of fresh input, so a
  flat per-token rate overstates a real run by ~10x. USD stays `null` unless
  `cost_envelope.usd_per_aiu` gives a rate, and an unrated run reports *unmetered*, never
  `0.00`.
- **Telemetry unavailable (exit 3) is a tooling failure, not a budget breach** — warn and
  continue. Halting delivery over a metering table is the wrong trade.

### Vendored skills
20 of the 61 skills are unmodified copies from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills),
indexed in `plugins/VENDORED.md` (which names the owning plugin per skill). **Do not edit
them in place** — extend via a wrapper skill, or contribute upstream and re-sync. The other
41 are hand-written or adopted and are the ones to edit — 38 repo-scope
(csharp/python-implementation, csharp/python-testing, dotnet/python-startup-discovery,
development-practices, testing-practices, data-science-practices, data-engineering-practices, code-review-checklist, artifact-coverage,
bicep/terraform-azure/helm-kustomize/cicd-pipeline-implementation, iac-best-practices,
architecture-design, architecture-decision-records, read-repo-context, engineering-standards,
engineering-judgement,
reviewer-read-only-rules, pr-description, release-notes, code-localisation, run-event-log,
test-bar-gate, e2e-testing, cost-budget, dev-lead-templates, backlog-item-standards,
ado-work-items, github-issues, azure-platform-grounding, deploy-verify,
solution-profile-interview, plus `polyglot-test-agent`, adopted after upstream deleted it)
plus the three user-scope skills below.

**Upstream has no integration- or application-smoke-testing skill.** That gap is why
`test-bar-gate`'s smoke slot and the two `*-startup-discovery` skills are hand-written; a
re-sync will not supply them. What upstream does cover — and what is vendored — is Bicep
deployment preflight and Playwright test generation.

`scripts/check-vendored-drift.ps1` fetches each entry and diffs it against the local copy,
ignoring only the `applies_to` line. Run it before a re-sync; hand the result to
`capability-scout` to decide what is worth taking.

### Personal preferences are not shipped
`trade-off-reporting`, `code-reviewer` and `cloud-native-patterns` once lived under a separate
`user/skills/` folder, because that is where they were first written — a person's own
`~/.copilot/skills/`. They now sit in `skills/` with everything else: all three are `applies_to:
all` engineering skills that the agents rely on, none is a personal preference, and both paths were
bundled identically anyway. **Do not re-split them** — a second skills folder needs its own
manifest entry, which is exactly the silent-drop failure the flat-layout rule above exists to
prevent, and it left contributors with no rule for which folder a new skill belongs in.

**Genuine personal preference stays out of the plugin entirely.** The suite ships
`engineering-standards` (the technology-neutral quality bar: Clean Code / SOLID / DDD /
Clean Architecture, security-by-default, operational practices, the pre-PR checklist) and
nothing about how any individual likes to be talked to. Tone, verbosity, proactivity and
how someone phrases a directive belong in that person's own `~/.copilot/skills/working-style/`,
outside the plugin — `read-repo-context` §3 honours one if present and falls back to the
repository's own instructions if not. **Never add a person's preferences to a plugin skill**:
this harness is installed by many people, and one person's tone is another's noise.

### Seniority is judgement, not looser gates (ADR 0013)
Agents are expected to behave like experienced practitioners: decide inside their mandate,
fill an under-specified request with the professional default, and escalate on
**reversibility × blast radius** — never on unfamiliarity or on "the request didn't say".
That posture lives in **one** place, the `engineering-judgement` skill, loaded silently on
every turn by `read-repo-context` §3. It pairs with `engineering-standards` the way a
practitioner pairs with a spec: standards are *what good looks like*, judgement is *how an
experienced person decides*. Each agent then carries a short **"The calls only you make"**
naming the judgement that role and no other exercises.

**This is an operating posture, not a personal preference** — which is why it ships inside
the plugin while `working-style` deliberately does not. The test is whether the content
would be the same for every user of the harness. "Escalate irreversible decisions" is;
"keep answers short and skip the preamble" isn't.

**Autonomy means fewer questions, never fewer controls.** Every human gate is unchanged and
must stay that way: plan approval, PR approval, human-only merge/complete/close, force-push
and production-deploy bans, reviewer read-only, the test-asymmetry rule, and the
negative-result rules. `engineering-judgement` §8 states the boundaries seniority never
licenses crossing — skipping verification, weakening a test, expanding scope, inventing a
fact, routing around a gate — and it exists precisely because without it the rest of that
skill reads as permission to be confident. **Do not "extend" the autonomy work by relaxing a
gate**; that was considered and rejected in ADR 0013.

**"Decide rather than ask" is half a rule — the other half is "expose it at the next gate".**
Deciding more is only safe because Stage 4 shows the human what was decided: derived
acceptance criteria, trade-offs, the consequential calls made without asking, risks and open
questions relayed from Research, and what dies if a feasibility task fails. `engineering-judgement`
§6 front-loads this (raise it at the earliest gate someone could act on it) and warns that
right-sizing cuts **artifacts and ceremony, never the effort spent understanding the problem** —
because §1 and §5 read together would otherwise licence skimming Research. **Never remove one
half of the pairing while keeping the other**: without the visibility, autonomy is a black box;
without the autonomy, the gate is an interrogation. Research and Plan are where a run is cheapest
to correct, so that is where the thinking is spent and where it is shown.

**Don't add an `autonomy_level` profile key.** It was rejected as the *"config knob for a
value that never changes"* `dev-lead`'s own rules forbid — the posture calibrates off
`identity.lifecycle_stage` and `engagement_context.engagement_type`, which already declare
blast radius.

**Terse is not senior.** The reviewers' rubrics and working-context blocks were deliberately
*not* trimmed: that content is reference material a review needs, not procedure the reviewer
should have internalised. Cutting it would produce a shorter agent that finds less. When
adding judgement, pay for it by deleting *procedure* — never by deleting *reference*.

### Model-tier convention
Each `.agent.md` declares a `model_tier` in frontmatter — `light` (orchestration: `dev-lead`),
`mid` (mechanical authoring: `coding`, `infrastructure`, `backlog-manager`), or
`heavy` (deep reasoning: `architect` and all review agents).

**Nothing reads it.** It is declared by all 15 agents and consumed by no script, no
manifest, and not by the CLI — whose own frontmatter field is `model`. Treat it as recorded
intent (the rationale lives in ADR 0007 and `cost-budget/references/tier-defaults.md`), keep
it accurate when editing, and do not expect changing it to change which model runs.

### Skill format
Every skill is `<skill-name>/SKILL.md` with YAML frontmatter (`name`, `description`,
`applies_to`). **`description` is what drives skill-invocation matching** — `applies_to` does
not (see below). The frontmatter is followed by the workflow in natural language; reference
files live in `<skill-name>/references/`, scripts in `<skill-name>/scripts/`.

`applies_to` declares the technology scope — `all` for a technique that holds in any
ecosystem, otherwise a comma-separated list of the ecosystems it actually assumes
(`dotnet`, `python`, `azure, terraform`, `kubernetes, helm, kustomize`, `docker`,
`github-actions`, …). It is **required on every skill**; a missing value is a defect, not
a default. The split today is 34 `all` / 26 scoped.

**Nothing reads it.** Like `model_tier`, it is declared on every skill and consumed by no
script, no manifest, and not by the CLI — it is a local field that upstream has no equivalent
for (which is why `plugins/VENDORED.md` lists it as the one sanctioned modification to a
vendored copy). It does **not** filter the matching pool: every installed skill is a candidate
on every task regardless of what it declares. Treat it as recorded intent — it tells a *human*
whether a skill belongs in core or a companion, and it is how `capability-scout` places an
adopted skill — but do not reason as though it constrains loading at run time.

The mechanism that genuinely limits what a project carries is therefore **the plugin split, not
this field**: a Python project installs no `agile-agents-dotnet`, so those skills are not in its
pool at all. That is why anything tied to one ecosystem belongs in a companion. Within a plugin,
a scoped skill is still a live candidate for every task — so keep descriptions specific enough
that a wrong match is unlikely, rather than relying on `applies_to` to prevent it.
(Same reasoning as `microsoft/hve-core`'s `coding-standards` skills and
`obra/superpowers-skills`' `languages:` field.)

### Plugin manifests and versioning
When you add/remove an agent or skill, the owning plugin auto-discovers it (its manifest
points at `agents/` / `skills/`, relative to that plugin root).

**Bump the version of every plugin whose files changed, in the same PR.** The version is
the delivery mechanism — an installed plugin picks up nothing until it moves, so an
unbumped fix ships to nobody. Bump in three places, kept consistent: that plugin's
`plugins/<name>/.github/plugin/plugin.json`, its `plugins[]` entry in
`.github/plugin/marketplace.json`, and `metadata.version` (which tracks `agile-agents-core`).

Leave untouched plugins alone — a bump with no content change publishes a release
identical to the last one and makes the number stop meaning anything.

`scripts/check-plugin-versions.ps1` enforces all of it, as the `plugin-versions` CI check.
Run it locally with `-BaseRef origin/main`; without a base ref it checks only that the
manifests and the marketplace agree. It was written after the rule had been missed twice,
and replaying it over the offending PR reproduces the miss — seven plugins changed, all
still on `0.1.0`.

It compares against the **merge base**, because bumping is per PR, not per commit. That
also sidesteps the trap that hid both misses from manual audit: anchoring on *"the last
commit that touched `plugin.json`"* and diffing **forward** cannot see a change made **in**
that same commit.

### solution-profile.yaml is the contract
The template in `plugins/agile-agents-core/skills/solution-profile-interview/references/`
defines the key names. When the harness and the template disagree, **move the harness onto
the template** — profiles already bootstrapped in consumer repos cannot be migrated.

This has forked twice, and both forks were invisible because a missing key reads empty and
does nothing: the cost gate read `per_run_max_usd` against a template defining
`max_usd_per_run` (words reversed, no per-phase key at all), and `code-localisation` read
four keys the template never had. A gate documented as non-negotiable could not fire.

So: adding a profile read means adding the key to the template in the same change, and any
key nothing reads is dead weight — `cicd.release_strategy` sat unread until `deploy-verify`
became its first consumer.

Watch the YAML 1.1 booleans: `deploy_verify: "off"` **must stay quoted**, or it parses as
`false` and compares unequal to every string branch.

### AGENTS.md generation
`AGENTS.md` is generated from `solution-profile.yaml` + agent/skill frontmatter by
`scripts/generate-agents-md.ps1` / `.sh`. The generator discovers **every**
`plugins/agile-agents*/skills` directory and tags each skill with its plugin. **Do not hand-edit
it** — the `agents-md-sync` workflow fails the build if it drifts. Re-run the generator and
commit the result after changing agents, skills, or the profile. The `.ps1` writes a stray
root `agents/` as a side effect; delete it before committing.

**The two generators must agree, and both ways they diverged were CI-only** — red on a
runner, unreproducible locally:
- **Locale.** `${#s}` and `${s:0:n}` count bytes under `C` and characters under UTF-8,
  while the `.ps1` always counts characters — so long skill descriptions truncated at
  different points depending on whether the runner set `LANG`.
- **`yq` on `PATH`.** A jq-only expression that mikefarah yq rejects made every list-valued
  field come back empty, with stderr suppressed. True on GitHub's runners, false on a
  typical dev box.

Both were invisible until this repo had a profile with populated lists. When touching
either generator, check parity with and without `yq`, and under `LC_ALL=C` as well as
UTF-8.

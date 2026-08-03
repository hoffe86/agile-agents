# Copilot Instructions — dev-agents

## Repository purpose

This repo implements an **agent harness for autonomous coding** — the orchestration
layer, specialist agent roster, skills, gates, and operational profile that let an
agentic CLI take a prepared requirement and drive it to a reviewed change without a
human in the loop between stages. The harness is what this repo builds; the code it
writes lives in *other* repos.

It ships as `dev-agents`, a portable GitHub Copilot CLI **plugin**. This repo is both
the source you edit and the installable plugin/marketplace that others consume.

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
hoffe86/agent` then `copilot plugin install dev-agents@dev-agents-marketplace`, plus whichever
`dev-agents-<technology>` companion plugins the project needs. The CLI loads `agents/`,
`skills/`, and `user/skills/` directly from each plugin (see
`plugins/<name>/.github/plugin/plugin.json`). Per-project config
(`solution-profile.yaml`) is copied into the target repo's `.github/`.

## Repository structure

```
agent/                               Marketplace root
├── .github/
│   ├── copilot-instructions.md      This file
│   ├── plugin/marketplace.json      Marketplace listing (dev-agents-marketplace, pluginRoot ./plugins)
│   └── workflows/agents-md-sync.yml AGENTS.md drift check
├── plugins/                         One folder per plugin
│   ├── VENDORED.md                  Index of vendored skills across all plugins
│   ├── dev-agents/                  The autonomous-coding agent harness
│   │   ├── .github/plugin/plugin.json   Copilot CLI plugin manifest (name: dev-agents)
│   │   ├── agents/                  11 *.agent.md (1 supervisor + 4 authors + 5 reviewers + backlog-manager)
│   │   ├── skills/                  33 technology-neutral repo-scope skills
│   │   └── user/skills/             5 user-scope skills (bundled into the plugin)
│   ├── dev-agents-dotnet/           5 skills — C# / .NET
│   ├── dev-agents-python/           4 skills — Python
│   ├── dev-agents-bicep/            2 skills — Bicep IaC
│   ├── dev-agents-terraform/        3 skills — Terraform IaC
│   ├── dev-agents-ado/              1 skill  — Azure DevOps Boards tracker mechanics
│   └── dev-agents-github/           1 skill  — GitHub Issues tracker mechanics
├── scripts/                         generate-agents-md.{ps1,sh} + references/
├── eval/                            Eval harness (SWE-bench subset + custom tasks) + baselines.md
├── docs/
│   ├── adr/                         Architecture decision records (0001–0007)
│   ├── research/                    Whitepaper + spikes
│   └── AGENTS-MD-MAPPING.md         Folder→agent mapping for the generator
├── solution-profile.yaml            Per-project operational profile (template)
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

**What belongs where.** `dev-agents` holds the agents and every **technology-neutral** skill.
Anything tied to one language, IaC tool, or tracker ships in a `dev-agents-<technology>`
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

### Hand-off block-name canon (do not change)
Worker agents emit a recognisable terminator block on completion — `dev-lead` parses these.
Renaming any silently breaks the pipeline:
- `IMPLEMENTATION COMPLETE` (coding)
- `TESTS COMPLETE` (testing)
- `INFRASTRUCTURE COMPLETE` (infrastructure)
- `ARCHITECTURE DESIGN COMPLETE` (architect)
- `REVIEW COMPLETE` (every review agent)
- `TASKS PLANNED` (backlog-manager — the Plan-phase task-creation hand-off)

### RPI pipeline + tasks-in-tracker
`dev-lead` orchestrates the **RPI pattern** — **Research → Plan → Implement → Review**:
- **Research** — read-only verification against the *already-prepared* concept (arc42 / C4)
  and accepted ADRs; delegates to `architect` when scope warrants. The pipeline conforms to
  those up-front decisions and never authors them; a missing decision is escalated to humans.
- **Plan** — decompose the story into independently-implementable tasks (acceptance criteria
  + approach note). When `backlog.create_tasks` is true, `backlog-manager` creates them as
  **child work items linked to the parent story** (provisional, tagged `pending-approval`)
  and emits `TASKS PLANNED`. The **mandatory human plan-approval gate fires after task
  creation**. Tasks live in the tracker, not as files — local handover files
  (`rpi.handover_dir`) are an ephemeral, gitignored cache.
- **Implement / Review** — coding + infrastructure + testing, then multi-lens review.

### Vendored skills
24 of the 49 skills across all plugins are unmodified copies from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills),
indexed in `plugins/VENDORED.md` (which names the owning plugin per skill). **Do not edit
them in place** — extend via a wrapper skill, or contribute upstream and re-sync. The 25
hand-written skills are the ones to edit (csharp/python-implementation,
csharp/python-testing, code-review-checklist,
bicep/terraform-azure/helm-kustomize/cicd-pipeline-implementation, iac-best-practices,
architecture-design, architecture-decision-records, read-repo-context,
reviewer-read-only-rules, pr-description, release-notes, code-localisation, run-event-log,
test-bar-gate, e2e-testing, cost-budget, dev-lead-templates, backlog-item-standards,
ado-work-items, github-issues).

### User-scope skills
The five skills under `user/skills/` (`working-style`, `trade-off-reporting`, `code-review`,
`cloud-native-patterns`, `azure-drawio-mcp-diagramming`) are referenced by **every** agent.
They are bundled into the plugin (the `skills` array includes `user/skills/`). If you also
keep a runtime copy at `~/.copilot/skills/`, sync changes both ways.

### Model-tier convention
Each `.agent.md` declares a `model_tier` in frontmatter — `light` (orchestration: `dev-lead`),
`mid` (mechanical authoring: `coding`, `infrastructure`, `testing`, `backlog-manager`), or
`heavy` (deep reasoning: `architect` and all review agents). Preserve the tier when editing;
downgrading a heavy agent silently degrades review quality.

### Skill format
Every skill is `<skill-name>/SKILL.md` with YAML frontmatter (`name`, `description`,
`applies_to`) used for skill-invocation matching, followed by the workflow in natural
language. Reference files live in `<skill-name>/references/`, scripts in
`<skill-name>/scripts/`.

`applies_to` declares the technology scope — `all` for a technique that holds in any
ecosystem, otherwise a comma-separated list of the ecosystems it actually assumes
(`dotnet`, `python`, `azure, terraform`, `kubernetes, helm, kustomize`, `docker`,
`github-actions`, …). It is **required on every skill**; a missing value is a defect, not
a default. The split today is 27 `all` / 20 scoped.

Why declare it rather than exclude tech-specific skills: skills load on demand, so a
scoped skill costs nothing when the task doesn't touch that ecosystem — but an
*undeclared* one sits in the same matching pool as the agnostic ones and can be pulled
into an unrelated task. Declaring the scope is what makes the on-demand model safe.
(Same reasoning as `microsoft/hve-core`'s `coding-standards` skills and
`obra/superpowers-skills`' `languages:` field.)

### Plugin manifests
When you add/remove an agent or skill, the owning plugin auto-discovers it (its manifest
points at `agents/` / `skills/` / `user/skills/`, relative to that plugin root). On a release,
bump `version` in **every** changed `plugins/*/.github/plugin/plugin.json`, in the matching
`plugins[]` entry of `.github/plugin/marketplace.json`, and in `metadata.version`.

### AGENTS.md generation
`AGENTS.md` is generated from `solution-profile.yaml` + agent/skill frontmatter by
`scripts/generate-agents-md.ps1` / `.sh`. The generator discovers **every**
`plugins/dev-agents*/skills` directory and tags each skill with its plugin. **Do not hand-edit
it** — the `agents-md-sync` workflow fails the build if it drifts. Re-run the generator and
commit the result after changing agents, skills, or the profile.

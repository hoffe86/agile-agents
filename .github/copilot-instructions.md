# Copilot Instructions — dev-agents

## Repository purpose

This repo is the **development home** of `dev-agents` — a portable GitHub Copilot CLI
**plugin** providing an autonomous software-development agent suite. It is both the
source you edit and the installable plugin/marketplace that others consume.

Two ways the suite is consumed:

1. **As a Copilot CLI plugin** (primary) — `copilot plugin marketplace add hoffe86/agent`
   then `copilot plugin install dev-agents@hoffe86-agent-marketplace`. The CLI loads
   `agents/` and `skills/` + `user/skills/` directly from the plugin (see
   `.github/plugin/plugin.json`).
2. **Vendored into a target repo** (copy-install) — `install.ps1` / `install.sh` copy
   the suite into a project's `.github/` (agents → `.github/agents/`, skills →
   `.github/skills/`). See `INSTALL.md`.

## Repository structure

```
agent/
├── .github/
│   ├── copilot-instructions.md      This file
│   ├── plugin/
│   │   ├── plugin.json              Copilot CLI plugin manifest (name: dev-agents)
│   │   └── marketplace.json         Marketplace listing (hoffe86-agent-marketplace)
│   └── workflows/agents-md-sync.yml AGENTS.md drift check
├── agents/                          11 *.agent.md (1 supervisor + 4 authors + 5 reviewers + backlog-manager)
├── skills/                          47 repo-scope skills + VENDORED.md
├── user/skills/                     5 user-scope skills (bundled into the plugin)
├── scripts/                         generate-agents-md.{ps1,sh} + references/
├── eval/                            Eval harness (SWE-bench subset + custom tasks) + baselines.md
├── docs/
│   ├── adr/                         Architecture decision records (0001–0007)
│   ├── research/                    Whitepaper + spikes
│   └── AGENTS-MD-MAPPING.md         Folder→agent mapping for the generator
├── solution-profile.yaml            Per-project operational profile (template)
├── install.ps1 / install.sh / INSTALL.md
├── AGENTS.md                        Generated — do not hand-edit
└── README.md
```

### Flat-layout rule
Copilot CLI does NOT support nested folders under `.github/agents/` or `.github/skills/`.
Every `*.agent.md` and every `skills/<name>/` subfolder must be **flat** — there are no
`coding/` or `backlog/` category folders.

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
26 of the 47 skills in `skills/` are unmodified copies from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills),
indexed in `skills/VENDORED.md`. **Do not edit them in place** — extend via a wrapper skill,
or contribute upstream and re-sync. The 21 hand-written skills are the ones to edit
(csharp/python-implementation, csharp/python-testing, code-review-checklist,
bicep/terraform-azure/helm-kustomize/cicd-pipeline-implementation, iac-best-practices,
architecture-design, architecture-decision-records, read-repo-context,
reviewer-read-only-rules, pr-description, release-notes, code-localisation, run-event-log,
test-bar-gate, e2e-testing, cost-budget).

### User-scope skills
The five skills under `user/skills/` (`working-style`, `trade-off-reporting`, `code-review`,
`cloud-native-patterns`, `azure-drawio-mcp-diagramming`) are referenced by **every** agent.
As a plugin they are bundled (the `skills` array includes `user/skills/`). For copy-install
they go to `~/.copilot/skills/`. If you also keep a runtime copy at `~/.copilot/skills/`,
sync changes both ways.

### Model-tier convention
Each `.agent.md` declares a `model_tier` in frontmatter — `light` (orchestration: `dev-lead`),
`mid` (mechanical authoring: `coding`, `infrastructure`, `testing`, `backlog-manager`), or
`heavy` (deep reasoning: `architect` and all review agents). Preserve the tier when editing;
downgrading a heavy agent silently degrades review quality.

### Skill format
Every skill is `<skill-name>/SKILL.md` with YAML frontmatter (`name`, `description`) used for
skill-invocation matching, followed by the workflow in natural language. Reference files live
in `<skill-name>/references/`, scripts in `<skill-name>/scripts/`.

### Plugin manifests
When you add/remove an agent or skill, the plugin auto-discovers them (the manifest points at
`agents/` and `skills/` + `user/skills/`). Bump `version` in both
`.github/plugin/plugin.json` and `.github/plugin/marketplace.json` on a release.

### AGENTS.md generation
`AGENTS.md` is generated from `solution-profile.yaml` + agent/skill frontmatter by
`scripts/generate-agents-md.ps1` / `.sh`. **Do not hand-edit it** — the `agents-md-sync`
workflow fails the build if it drifts. Re-run the generator and commit the result after
changing agents, skills, or the profile.

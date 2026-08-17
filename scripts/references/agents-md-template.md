<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->
# AGENTS.md — {{PROJECT_NAME}}

> Generated from `solution-profile.yaml` on {{GENERATED_ON}}.
> Do not edit by hand — regenerate with `scripts/generate-agents-md.ps1` (or `.sh`).

This file follows the cross-vendor [AGENTS.md](https://agents.md) convention so that
agentic CLIs (Claude Code, Copilot CLI, Cursor, Aider, …) can pick up a portable
description of how this repository expects autonomous agents to behave. The
authoritative, richer machine-readable contract remains
[`solution-profile.yaml`](solution-profile.yaml) plus the per-agent
[`*.agent.md`](.github/agents/) files.

## Project context

- **Project**: {{PROJECT_NAME}}
- **Primary language(s)**: {{LANGUAGES}}
- **Backlog platform**: {{BACKLOG_PLATFORM}}
- **Documentation**: {{DOC_LOCATION}} (platform: {{DOC_PLATFORM}})
- **Branch naming**: {{BRANCH_NAMING}}
- **Commit convention**: {{COMMIT_CONVENTION}}
- **Default branch**: {{DEFAULT_BRANCH}}

## How to interact

This repository runs a **supervisor + specialist** topology. The
`dev-lead` agent drives the **RPI pattern** (Research → Plan → Implement
→ Review): it researches against the prepared concept + ADRs, decomposes
the story into tasks that `backlog-manager` creates as child work items in
the tracker (approved by a human), then delegates to the specialist agents
in sequence (architect → coding → infrastructure → review
fan-out). Each worker emits a **sentinel hand-off block** on
completion — those block names are canonical and parsed by
`dev-lead`:

- `IMPLEMENTATION COMPLETE` (coding — production code **and** the tests covering it)
- `ANALYSIS COMPLETE` (data-scientist — an answer plus its evidence)
- `INFRASTRUCTURE COMPLETE` (infrastructure)
- `ARCHITECTURE DESIGN COMPLETE` (architect)
- `REVIEW COMPLETE` (review-lead — the specialist reviewers report into it)
- `TASKS PLANNED` (backlog-manager)
- `BOOTSTRAP COMPLETE` (bootstrapper)

Agents branch, commit and push on their own — on a feature branch, never the default one.
**Opening a pull request needs the user's explicit approval**, and **completing, merging or
closing a PR is human-only, always**, as are force-pushing, rewriting shared history and
production deploys. Deployments to non-production run through the project's own pipeline and are gated
on `infrastructure.deploy_verify`. Reviewers are **read-only**. See `.github/AGENTS-MD-MAPPING.md` for the
full convention map.

## Agents

{{ACTIVE_AGENTS_TABLE}}

## Skills

The following skills are available in `.github/skills/` (or
`skills/` at the repo root in the agile-agents source). Each skill
is a self-contained `<name>/SKILL.md` with YAML frontmatter and a
natural-language workflow.

{{SKILLS_LIST}}

Mandatory-load skills (loaded by every agent regardless of context):

{{MANDATORY_SKILLS_LIST}}

## Cost & evaluation

- **Evaluation harness**: {{EVAL_POINTER}}
- **Cost envelope**: see `solution-profile.yaml` → `cost_envelope` and
  the `cost-budget` skill for per-phase / per-run USD ceilings and
  model-tiering policy.
- **Run event log**: structured JSON events at
  `.copilot-runs/<run-id>/events.jsonl` — schema in
  `skills/run-event-log/SKILL.md`.

---

_Generated from `solution-profile.yaml` — do not edit by hand;
regenerate with `scripts/generate-agents-md.ps1`._

## Tokens

> This section is **stripped from the generated `AGENTS.md`**. It
> documents every placeholder token the generator script must
> substitute when rendering this template.

| Token | Source field(s) | Notes |
|-------|----------------|-------|
| `{{PROJECT_NAME}}` | `identity.project_name` | Falls back to repo folder name. |
| `{{GENERATED_ON}}` | runtime (UTC, `yyyy-MM-dd`) | Date only, for determinism. |
| `{{LANGUAGES}}` | `tech_stack.primary_languages[].name(@version)` | Comma-joined; `unspecified` if empty. |
| `{{BACKLOG_PLATFORM}}` | `backlog.platform` | `unspecified` if empty. |
| `{{DOC_LOCATION}}` | `documentation.location` | `unspecified` if empty. |
| `{{DOC_PLATFORM}}` | `documentation.platform` | `unspecified` if empty (agents assume `in-repo`). |
| `{{BRANCH_NAMING}}` | `backlog.branch_naming` | `unspecified` if empty. |
| `{{COMMIT_CONVENTION}}` | `backlog.commit_convention` | `unspecified` if empty. |
| `{{DEFAULT_BRANCH}}` | `identity.default_branch` | Defaults to `main`. |
| `{{ACTIVE_AGENTS_TABLE}}` | walk `.github/agents/*.agent.md`, filter by `ai_copilot.active_agents` | One `### name` block per agent with description, tools, sub-agents. Sorted alphabetically. |
| `{{SKILLS_LIST}}` | walk `*/SKILL.md`, take frontmatter `name` + first sentence of `description` | Bulleted list, sorted alphabetically. |
| `{{MANDATORY_SKILLS_LIST}}` | `ai_copilot.mandatory_skills` | Bulleted list; `_(none configured)_` if empty. |
| `{{EVAL_POINTER}}` | presence of `eval/` directory | If present: `see ./eval/` else: `not configured (see plan H2)`. |

<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->
# AGENTS.md — {{PROJECT_NAME}}

> Generated from `solution-profile.yaml` on {{GENERATED_ON}}.
> Do not edit by hand — use the `solution-profile-interview` skill's bundled generator
> (this harness repository also provides `scripts/generate-agents-md.ps1` / `.sh` wrappers).

Portable context using the [AGENTS.md](https://agents.md) convention.
The authoritative contracts are `.github/solution-profile.yaml` (or the explicit
profile selected for generation), repository instructions and the configured
`*.agent.md` files.

## Project context

- **Project**: {{PROJECT_NAME}}
- **Primary language(s)**: {{LANGUAGES}}
- **Backlog platform**: {{BACKLOG_PLATFORM}}
- **Documentation**: {{DOC_LOCATION}} (platform: {{DOC_PLATFORM}})
- **Branch naming**: {{BRANCH_NAMING}}
- **Commit convention**: {{COMMIT_CONVENTION}}
- **Default branch**: {{DEFAULT_BRANCH}}

## How to interact

`dev-lead` supervises Research → Plan → Implement → Review against prepared
decisions. Plans need human approval; tracker tasks are conditional on the
profile. Authors work sequentially and own their tests; reviewers are independent.
Workers return these canonical hand-off blocks:

- `IMPLEMENTATION COMPLETE` (coding — production code **and** the tests covering it)
- `ANALYSIS COMPLETE` (data-scientist — an answer plus its evidence)
- `INFRASTRUCTURE COMPLETE` (infrastructure)
- `ARCHITECTURE DESIGN COMPLETE` (architect)
- `REVIEW COMPLETE` (review-lead — the specialist reviewers report into it)
- `TASKS PLANNED` (backlog-manager)
- `BOOTSTRAP COMPLETE` (bootstrapper)

Feature-branch creation, commits and pushes need no harness gate, but explicit
user restrictions and stricter personal consent still apply.
**Opening a pull request needs the user's explicit approval**, and **completing, merging or
closing a PR is human-only, always**, as are force-pushing, rewriting shared history and
production deploys. Deployments to non-production run through the project's own pipeline and are gated
on `infrastructure.deploy_verify`. Reviewers are **read-only**.

## Agents

{{ACTIVE_AGENTS_TABLE}}

## Skills

Skills discovered from the configured directories; availability alone does not
prove applicability or invocation. Respect native scope and tool grants.

{{SKILLS_LIST}}

Mandatory-load skills (loaded by every agent regardless of context):

{{MANDATORY_SKILLS_LIST}}

## Cost & evaluation

- **Evaluation harness**: {{EVAL_POINTER}}
- **Cost envelope**: `cost_envelope` and `cost-budget` gate measured AIU/tokens.
  USD is unmetered without a rate; model tiers are advisory, not runtime enforcement.
- **Run event log**: structured JSON events at
  `.copilot-runs/<run-id>/events.jsonl` — `run-event-log` defines the schema;
  only `dev-lead` emits events.

## Tokens

Generator placeholders; this section is excluded from output.

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
| `{{EVAL_POINTER}}` | presence of `eval/` directory | If present: `see ./eval/`; otherwise `not configured`. |

# AGENTS.md ↔ solution-profile.yaml — mapping & conventions

## Why both files exist

We deliberately keep **two** sources of agent configuration:

1. **`solution-profile.yaml`** — the rich, typed, **authoritative** project
   config. Schema-validated, machine-readable, organised by concern
   (identity, tech stack, infrastructure, compliance, ai_copilot, …). Every
   agent in this suite reads it first; `dev-lead` halts at Stage 0 if any
   required field is missing. Whitepaper §6.3 C5 explicitly **rejects**
   replacing it with AGENTS.md — typed YAML enables schema validation and
   richer field semantics that AGENTS.md cannot express.

2. **`AGENTS.md`** — the **portable, vendor-neutral projection** of the
   profile that other agentic CLIs can consume. Auto-generated from
   `solution-profile.yaml` + `*.agent.md`. Never edit by hand — every edit
   would be lost on the next regeneration.

This is the same pattern as `package.json` (rich, typed) ↔ `README.md`
(human-readable summary): one is the source of truth, the other is a
distributable view.

## Convergence on AGENTS.md

The cross-vendor [AGENTS.md](https://agents.md) convention emerged in 2025
as the de-facto portable agent-context file, with first-party support
landing in Claude Code, Copilot CLI, Cursor compose, and Aider. Generating
it from our richer profile means a downstream fork is **portable to other
CLIs without losing our richer model**.

> See `docs/research/sources/stream-e-blogs.md` §"AGENTS.md Convergence"
> for the cross-vendor adoption evidence.

## Mapping table

| `solution-profile.yaml` field | `AGENTS.md` section |
|------|------|
| `identity.project_name` | `# AGENTS.md — <name>` header + `## Project context` |
| `identity.default_branch` | `## Project context` → Default branch |
| `documentation.docs_root` | `## Project context` → Documentation root |
| `backlog.system` | `## Project context` → Backlog system |
| `backlog.branch_naming` | `## Project context` → Branch naming |
| `backlog.commit_convention` | `## Project context` → Commit convention |
| `tech_stack.primary_languages[]` | `## Project context` → Primary language(s) |
| `ai_copilot.active_agents[]` | filter for `## Agents` (only listed agents render) |
| `ai_copilot.mandatory_skills[]` | `## Skills` → Mandatory-load skills |
| `cost_envelope.*` (referenced) | `## Cost & evaluation` → pointer back to profile |
| `eval/` directory presence | `## Cost & evaluation` → Evaluation harness link |

The per-agent description, tools, and sub-agent list come from each
agent's own YAML frontmatter in `.github/agents/*.agent.md`. The skill
catalogue comes from each `<skill>/SKILL.md` frontmatter.

## Re-generation policy

- **Run after every edit** to `solution-profile.yaml`, any `*.agent.md`
  frontmatter, or any `SKILL.md` frontmatter:

  ```powershell
  ./scripts/generate-agents-md.ps1
  ```

  ```bash
  ./scripts/generate-agents-md.sh
  ```

- **Optional CI check** (recommended for downstream forks): run the
  generator with `--dry-run` and `git diff --exit-code AGENTS.md` — fail
  the build if AGENTS.md drifts from the profile. This is a
  copy-paste-ready GitHub Actions step:

  ```yaml
  - name: AGENTS.md is in sync with profile
    run: |
      ./scripts/generate-agents-md.sh
      git diff --exit-code AGENTS.md
  ```

- The generator is **deterministic**: identical inputs produce
  byte-identical output (agents and skills sorted alphabetically,
  timestamp date-only UTC). No cache invalidation needed.

## Compatibility notes

| CLI | Honours `AGENTS.md` | Honours `*.agent.md` directly | Notes |
|-----|---------------------|-------------------------------|-------|
| Copilot CLI | ✓ | ✓ (primary) | Reads `.github/agents/*.agent.md` first; AGENTS.md is supplementary context. |
| Claude Code | ✓ (primary) | ✗ | Treats AGENTS.md as the canonical agent-context file. |
| Cursor compose | ✓ | ✗ | Loads AGENTS.md when present in repo root. |
| Aider | ✓ (best-effort) | ✗ | Reads AGENTS.md alongside its own conventions file. |
| Other / unknown | gracefully ignores | gracefully ignores | The file is plain markdown — no breakage. |

## What goes where (decision guide)

- **Add a new typed field, a constraint, or anything a script needs to
  read** → `solution-profile.yaml` (extend the schema; document in
  comments).
- **Change agent prose, descriptions, or sentinel-block conventions** →
  edit the relevant `*.agent.md` file or `SKILL.md`; AGENTS.md picks it
  up on next regeneration.
- **Want to add a new vendor-neutral hint** that has no place in the
  typed profile → extend `scripts/references/agents-md-template.md`
  (and document the new token in its `## Tokens` section).
- **Never** hand-edit `AGENTS.md` — your changes will be lost.

## Out-of-scope for the generator

- Skill audit/conformance to the AgentSkills.io spec — that is a
  separate Wave-2 task (see plan H5 part A).
- Vendored skills (26 of 42 in `skills/`) — re-sync upstream from
  `github/awesome-copilot`; do not edit in place.

## Status: adopted & CI-enforced (2026-05-08)

`AGENTS.md` is now committed at the template repo's (simulated) root —
[`AGENTS.md`](../AGENTS.md) — and kept in sync by the
[`agents-md-sync`](../../../.github/workflows/agents-md-sync.yml) GitHub
Actions workflow. The workflow re-runs `generate-agents-md.ps1` on every
push / PR that touches `solution-profile.yaml`, any `*.agent.md`, any
`SKILL.md`, or the generator scripts, then fails the build if
`git diff --exit-code AGENTS.md` reports drift. A
`workflow_dispatch` trigger is available for manual regeneration.

This means the **copy-paste CI snippet above is no longer optional for
this repo** — it is wired up. Downstream forks should keep the same
workflow when they adopt the suite.

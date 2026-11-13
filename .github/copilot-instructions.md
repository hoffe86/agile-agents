# Copilot Instructions — Agile Agents

## Purpose and ownership

This repository builds the Agentic Agile Harness: RPI orchestration, specialist
roles, gates and evidence contracts. Its agents write software in consuming
solutions. Treat prompt edits here as runtime behavior changes, not mere docs.

This repository implements **only `agile-agents-core`**. The shared
`agentic-universe` also lists the independently maintained, optional
`agentic-persona` through an external GitHub source, never as a core dependency
or vendored copy. Solutions own technical,
framework, cloud and tracker guidance and verification commands. Users select
optional personal tooling; no personal package is required. Do not build another
technical catalog or copy retired recipes into local skills/references/fixtures.
Distribution retirement does not uninstall consumer copies. See
[ownership and rollback](../docs/customization-ownership.md).

Discover scoped instructions, local skills, installed plugins and existing
CI/check commands before proposing gaps. Match descriptions/capabilities and
task/path/stack/version/provider/role applicability, not historical names.
Respect `applyTo`, directory scopes and native delivery; on-disk files do not
prove runtime availability or automatic injection. Do not invent precedence,
commands or a resolver. Missing optional depth uses repo/provider conventions
and authoritative docs, with the fallback reported.

Personal preferences may require stricter consent, never waive safety, approval,
reviewer boundaries or solution constraints. `capability-scout` proposes trusted
improvements with provenance, licensing, overlap, ownership and a before/after
evaluation; humans approve adoption and installation.

## Inventory and layout

- 15 *.agent.md files under `plugins/agile-agents-core/agents/`.
- 25 repo-scope skills under `plugins/agile-agents-core/skills/`.
- 5 workflows under `.github/workflows/`.
- Architecture decision records (0001–0015) under `docs/adr/`.
- 1 of the 25 skills is an unmodified copy (apart from the scope annotation).
24 are hand-written or adopted. `plugins/VENDORED.md` is the current upstream index.
- Scope split today is 25 `all` / 0 scoped.

Keep agents and skill folders flat: manifests discover only the declared paths,
relative to the plugin root. `.github/plugin/marketplace.json` lists local core
and external persona under one marketplace identity;
`plugins/agile-agents-core/.github/plugin/plugin.json` owns its manifest.
No agents or distributed skills at repository root.

## Context and decisions

Load `read-repo-context` first; its `engineering-judgement` dependency owns
mandate, escalation and concise trade-off reporting. Author self-checks live in
`development-practices`; testing in `testing-practices`; specialized review
rubrics in reviewer agents. Do not duplicate generic tutorials or development
history in skills. `acquire-codebase-knowledge` is explicit onboarding only.

The solution profile's declared values override defaults, never safety.
Its template defines stable keys: move readers onto it, not consumers onto a new
schema. Keep the six required fields, explicit enabled gate commands, all five
`testing.e2e` fields and quoted `"off"` values. Enabled checks with missing
commands fail configuration; disabled checks remain visible skips. Undetermined
startup blocks verified Done. Preserve both shell runners' exit/readiness,
deadline and owned-process cleanup behavior.

Read accepted ADRs relevant to the change; no autonomous ADR writing. Missing
material decisions are human decision gaps; no ADR adoption requirement for
projects that do not use them. Cite binding decisions and profile fields.
Autonomy reduces questions, never controls: show consequential assumptions,
trade-offs, risks and downstream consequences at the earliest actionable gate.

## Roles, gates and evidence

`dev-lead` coordinates Research → Plan → Implement → Review:

- Research verifies prepared concepts/decisions and source evidence.
- Plan decomposes into tasks; `backlog-manager` creates provisional linked
  children when enabled. Human approval follows task creation.
- After approval, `dev-lead` may author an approved application/IaC task and its
  tests directly or delegate it to `coding` / `infrastructure`, one task at a
  time. Data-science analysis remains delegated to `data-scientist`; authors
  own their tests. This task-level author choice follows the approved
  [ADR 0009 amendment](../docs/adr/0009-merge-coding-and-testing-agents.md).
- Direct authorship does not waive the deterministic test bar, independent
  review, human-only operations, or role boundaries. `dev-lead` never reviews
  its own work.
- Never weaken/delete/skip tests to manufacture green. Justify every existing
  test change in `Existing tests modified`; test-reviewer adjudicates it.
- The deterministic test bar precedes independent review. `review-lead` performs
  no lens: always code-reviewer and security-reviewer, including docs-only diffs
  and mandatory secret scanning; add other specialists by applicability.
- Reconcile verbatim intake acceptance criteria with actual test/review evidence
  at Stage 9. Task status alone is not delivery evidence.
- Preserve fail-closed approval transport, command evidence and reviewer
  forbidden-workflow checks in evaluators. Never soften task expectations to
  conceal missing solution guidance.

Tracker states are neutral: `in_progress`, `implemented`, `blocked`, `done`.
`backlog-manager` maps them from profile or accepted tracker values. If
`implemented` is unavailable, keep state and comment; never close early.
Failed task creation halts; failed status mirroring warns and continues.

Canonical sentinels must not change:
`IMPLEMENTATION COMPLETE`, `ANALYSIS COMPLETE`, `INFRASTRUCTURE COMPLETE`,
`ARCHITECTURE DESIGN COMPLETE`, `REVIEW COMPLETE`, `TASKS PLANNED`,
`BOOTSTRAP COMPLETE`. Load only the matching hand-off section. `TESTS COMPLETE`
is not a separate author gate. Negative/inconclusive analysis is a valid outcome.
Malformed hand-offs get one corrective request, then stop.

## Write permissions and tools

Feature-branch creation, scoped commits and pushes need no harness approval;
explicit user restrictions and stricter consent still apply. Opening a PR needs
explicit per-run approval, separate from plan approval. Merge/complete/close,
force-push, shared-history rewrite, shared-branch deletion and production
deployment are human-only. Non-production deployment uses the project's pipeline
and `infrastructure.deploy_verify: dev`, excluding the final or prod-named stage.
Reviewers and `capability-scout` remain effect-based read-only / proposal-only
regardless of tool availability; these are role contracts, not technical
tool-denials.

PR publication follows `identity.repo_url`, not `backlog.platform`.
Git safety/conventions: `development-practices` §10. Publication evidence:
`dev-lead-templates/references/completion.md`. Report permission boundaries as
such, not as missing MCP tools.

All 15 agent definitions use `tools: ["*"]` to expose tools made available
through runtime, workspace, or global configuration. This does not register an
absent server, grant authorization to an external service, or bypass local/host
restrictions. Skill `allowed-tools` grants nothing. Tool grants do not
technically deny reviewers or `capability-scout` write-capable tools: reviewers
must remain read-only by effect, and `capability-scout` proposal-only, as
specified by their role contracts. Reviewers may read/navigate but not edit
files, submit forms, mutate state, authenticate through a console, or execute
unsafe browser code; `reviewer-read-only-rules` is authoritative.

## Usage and models

Only `dev-lead` emits run events. Pair every phase_start with phase_complete.
No self-reported token/cost fields: collect CLI usage with `collect-usage.py`.
Gate on measured AIU/tokens, not USD; USD is null without a rate. Unavailable
telemetry (exit 3) warns, not a budget breach. Never invent zero usage.

Keep `metadata.model_tier`: mid for coding, infrastructure, backlog-manager,
bootstrapper; heavy for the other 11 agents (ADR 0007). Native model selection
is separate. No shipped model pins or profile-derived task overrides.
The profile/template checker validates model-ID lists against approved IDs;
it does not enforce runtime governance. Optional setup is user-approved manual
`/subagents`, never user/global settings writes or silent fallback.
Read `cost-budget/references/tier-defaults.md` for native setup/version limits.

## Artifact format, checks and versions

Skills require matching folder/name, valid YAML, `description: >-`, and nonempty
`metadata.applies_to`. Scope is advisory, not runtime filtering. Preserve
upstream metadata types; reject duplicate keys, legacy top-level annotations
and native fields hidden in metadata. Agents require string metadata maps and
the exact tier inventory. Agent and skill names must not collide.

Keep entry points short and load references on demand. `.waza.yaml` token limits
are ratchets: never raise caps to pass. Measure before/after; do not claim model
equivalence from token counts. Version changed plugins once per PR in manifest,
marketplace entry and marketplace metadata; core remains **0.17.0** when its
files are unchanged. Metadata tracks core, not catalog-only changes. External
plugin releases belong to their source repository; verify its live manifest
when updating its listing. Check against the PR merge base.

`AGENTS.md` is generated, never hand-edited. Run `scripts/generate-agents-md.ps1`
and `.sh`; verify parity with/without isolated yq and C/UTF-8 locales. Remove only
the generator's empty root `agents/` side effect if created.
`check-instructions-drift.py` validates the countable claims above; unknown or
stale claims fail, not disappear behind filters.

Use the repo's declared checks:

- `python scripts/run-repo-checks.py lint`
- `python scripts/run-repo-checks.py unit`
- `pwsh -NoProfile -File scripts/check-skill-tokens.ps1`

The full unit command requires the hash-locked `eval/deepeval` environment and
PowerShell; preserve CI's unittest/pytest split. Report environment blockers and
actual commands/results, never predicted green. No unrelated fixes.

The custom-eval runner records command results and request-bound simulated
approval evidence; its scorer reads evidence without executing workspace code.
Simulation is eval-only, never a substitute for the harness's human approval.

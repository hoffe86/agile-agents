---
name: read-repo-context
description: >-
  Required agent preamble: scoped repo instructions, solution profile, engineering
  judgement, capability discovery, decision capture and hand-off validation.
  Load first, then apply role-specific profile fields and relevant guidance.
metadata:
  applies_to: all
---

# Read Repo Context

Apply the context steps before role-specific work; load later references only when needed.

## 1. Read repo-level instructions

Discover `.github/copilot-instructions.md`, `AGENTS.md`, and any equivalent the
active client supports. Discover nested instructions and
`.github/instructions/**/*.instructions.md` without blanket-loading them:
respect `applyTo`, directory scopes and the client's native mechanism for the
paths being touched. Recheck scope when the task reaches another path. A file's
presence does not prove native injection; reading it manually is not evidence
of automatic selective loading.

Apply relevant repo conventions (stack, testing, docs, commands) over agent
defaults, without waiving safety, approvals or reviewer read-only boundaries.
Do not assert universal precedence between native sources; surface unresolved
conflicts with their source and scope.

## 2. Load `.github/solution-profile.yaml`

**Profile fields override agent defaults**, never safety/security. Honour the
calling role's field list:

- If missing, report it to the orchestrator/user; `bootstrapper` owns the interview and approved setup. Do not improvise a profile.
- If a specific field you need is empty, ask the user once for that field — do not guess.
- Cite the profile field path (e.g. `solution-profile.yaml: tech_stack.test_discipline`) in your hand-off when it shaped a non-trivial choice.

## 3. Shared judgement and conditional guidance

- **`engineering-judgement`** — load silently: mandate, escalation, assumptions,
  trade-offs and unchanged approval/safety boundaries.
- **`cloud-native-patterns`** — load for external boundaries, shared resources, background work, startup / shutdown, or a new deployable. Canonical neutral patterns for resilience, 12-Factor readiness, observability and API hygiene. Packages, providers and configuration come from applicable available solution guidance, not this catalogue.

`code-review` is the human-requested whole-repo audit, not a pipeline diff review.
For diffs, `review-lead` dispatches specialist rubrics. Do not mix workflows.

**Optional personal guidance** comes from user-selected native instructions,
skills or plugins, with no required name or package. Absence is normal: use repo
conventions and shared standards. Honour applicable written preferences, including
stricter personal consent; they cannot waive harness approvals, safety or reviewer
boundaries, or supersede solution technical constraints. Never invent, author or
activate preferences for someone. Report conflicts, not an invented precedence.

### Discover capabilities before proposing gaps

Inspect native available skill descriptions, solution-local skills (including
`.github/skills/*/SKILL.md`), and already-installed plugins. Distinguish runtime
availability from merely on-disk source. Match capabilities and applicability
(task, paths, stack/version, provider and role), not historical skill names or a
companion catalog. `metadata.applies_to` is not runtime loading enforcement.
Load only relevant guidance; reviewers read reference material, never execute
an author workflow. Existing CI, scripts and profile commands are evidence for
verification; do not invent commands or a competing registry/resolver.

Check availability and grants separately: a tool may be absent from runtime
availability (for example, its server is not registered), or available but
omitted by a narrow agent `tools:` grant. `tools: ["*"]` covers the agent-level
grant check for tools the runtime makes available; it does not register servers,
authorize use, or bypass host permissions or workspace/global restrictions. If
use is denied despite an agent grant, report the permission boundary rather than
a missing tool. Native `skill` invocation needs a `skill` grant (explicit or
wildcard); a skill's `allowed-tools` grants nothing. Do not infer absence from a
failed load or recommend installation solely from a filename.
Without matching optional guidance, use repo conventions and authoritative
documentation, and report the fallback. Approval still gates adoption/install.

## 4. Decision-record check (advisory)

`documentation.adr.format: none`, or empty `adr.location` without an ADR folder,
means ADRs are not used. Do not create a folder, recommend adoption unasked or
raise missing ADRs as findings; use §5.

Otherwise scan the declared location, falling back to `docs/adr/`,
`docs/architecture/decisions/` or `architecture/decisions/`. Read relevant accepted
records before authoring. They are binding: cite ids and stop on conflicts.

**No agent authors an ADR on its own initiative.** Surface undecided questions
as decision gaps. `architect` may suggest a body in chat; only an explicit human
request invokes `architecture-decision-records` in a write-capable context.

## 5. Decision capture (applies whether or not ADRs are used)

Material decisions need durable rationale: accepted ADR, design-doc decision
section (arc42 §9 by default), work item or PR. If none records the decision,
surface a **decision gap**: decision needed · impact · options · recommendation.
Let a human settle it in the project's chosen form.

## 6. Code localisation (on-demand, code-touching tasks only)

For changes that touch source code in a non-trivial-sized repository, also load the **`code-localisation`** skill. It returns a ranked list of relevant files using the backend chosen in `solution-profile.yaml: code_localisation.backend` (default `tree-sitter`).

Skip for: IaC-only changes, doc-only changes, single-file edits with an explicit path, repos under ~30 source files.

Pass the localisation result forward in your hand-off so downstream agents (reviewers in particular) don't re-run localisation.

## 7. Receiving a hand-off from another agent

On receipt of a canonical block, read only the level-two section whose heading
equals the received sentinel in [handoff-contracts.md](references/handoff-contracts.md).
For corrective hand-offs also read
[Corrective accounting](references/handoff-contracts.md#corrective-accounting).
Resolve links relative to this loaded core skill file, not the consumer repository's
working directory. Missing/mismatched file or section: stop and surface a malformed
contract/context; do not reconstruct the schema or preload all sections.

For these blocks or a Stage-1 brief from a supervisor:

- Required fields must be complete, unambiguous and consistent; never infer scope,
  target SHA, NFRs or constraints.
- **One corrective request, then stop.** Name missing/malformed fields to the
  upstream caller. If still malformed, stop; under `dev-lead`, surface its
  malformed-hand-off stop condition. This includes read-only roles.

## 8. Improvements you notice along the way

Report out-of-scope improvements to the user or supervisor's Follow-ups; never
implement them in-run. Reviewers include proposed skill edits in their report,
not the workspace.

## 9. Verify before you assume

Use available documentation tooling: `context7/*` for library/API reference,
`microsoft-docs/*` for Microsoft material, `web` or registered vendor servers.

Verify uncertain, consequential API signatures, defaults, versions, limits,
deprecations, config keys and schemas before writing.

**Cheapest authoritative source first:**

1. **This repo** — existing usage, lockfiles and installed version; current docs
   are not evidence for a different pinned version.
2. **The profile** — `tech_stack.*` names the versions the answer has to be true for.
3. **Documentation tooling** — `context7` / `microsoft-docs` / the vendor's own MCP server.
4. **`web`** — whatever the above don't cover.

If tooling is unavailable, distinguish runtime absence/unregistered servers,
omitted agent grants (an exact grant is needed only for a narrow `tools:` list;
`"*"` covers that grant check), and host/workspace/global restrictions that may
deny use despite a grant. Recommend only evidence-supported fixes; otherwise
report the uncertainty and impact. Continue only within the task's gates; label
the unverified fact and impact in the hand-off. Cite sources and applicable
versions for consequential choices.
Reviewers also verify factual claims; read-only forbids writes, not lookup.
Skip redundant research for settled repo facts and stable language basics.

## After loading this skill

The calling agent then:

1. States its role-tailored profile-field-honour list (which fields it depends on).
2. Selects applicable role-specific capabilities by description.
3. Applies its role's rubric; authors use `development-practices`' Pre-PR
   self-check, while `review-lead` owns independent diff reviews.
4. Begins the workflow.

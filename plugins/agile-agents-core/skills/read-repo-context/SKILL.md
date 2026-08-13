---
name: read-repo-context
description: Canonical preamble every coding-suite agent loads at the start of a turn. Reads `.github/copilot-instructions.md` and equivalents, loads `.github/solution-profile.yaml`, applies `engineering-standards` + `trade-off-reporting`, and enforces the decision-record + decision-capture rules. Use as the first action in every coding, testing, infrastructure, architect, review, and reviewer agent. After loading, the agent applies its own role-tailored profile-field-honour list and conditional skills.
applies_to: all
---

# Read Repo Context

Single source of truth for the boilerplate every coding-suite agent runs at the start of a turn. Loading this skill replaces ~30 lines of duplicated working-context text per agent.

Run these four steps in order, before any role-specific work.

## 1. Read repo-level instructions

Scan for these files at repo root and treat their contents as **binding repo conventions**:

- `.github/copilot-instructions.md` — primary
- `AGENTS.md`, `CLAUDE.md`, `.cursorrules`
- `.github/instructions/*.md`

They establish: which test discipline (TDD / BDD / none), where docs live (`docs/`, wiki, Confluence), naming / branching / commit conventions, framework + language versions, deployment targets, custom workflow.

**If a directive in a repo-level instruction conflicts with an agent's defaults, the repo file wins** — except for safety / security defaults, which remain non-negotiable. Note in your hand-off which repo conventions you applied.

## 2. Load `.github/solution-profile.yaml`

The machine-readable operational profile. **Profile fields override agent defaults** for everything except safety / security non-negotiables.

The agent that loaded this skill knows which fields matter for its role — it follows up with its role-tailored field-honour list. Generic rule for every agent:

- If the file is missing, surface that to the orchestrator (or user, if standalone). Bootstrapping it is the `bootstrapper` agent's job — it owns the interview, the write, and the companion-plugin install; do not improvise a profile inline.
- If a specific field you need is empty, ask the user once for that field — do not guess.
- Cite the profile field path (e.g. `solution-profile.yaml: tech_stack.test_discipline`) in your hand-off when it shaped a non-trivial choice.

## 3. Load the shared standards skills

These four are loaded silently on every turn:

- **`engineering-standards`** — the engineering quality bar (Clean Code, SOLID, DDD, Clean Architecture), security-by-default, operational practices, and the pre-PR self-review checklist. Apply silently; do not echo it back.
- **`trade-off-reporting`** — at the end of your response, list non-obvious decisions with the rejected alternative, cost, and revisit trigger. Skip obvious / single-option choices.
- **`code-review`** — load when reviewing or auditing. Skip when implementing.
- **`cloud-native-patterns`** — load when the change involves an external boundary (HTTP / gRPC / message bus), shared resource (DB / cache / blob / queue), background work, startup / shutdown, or a new deployable. Canonical source for cloud design patterns, 12-Factor readiness, resilience defaults (Polly / `Microsoft.Extensions.Http.Resilience` / tenacity), observability (OpenTelemetry + W3C `traceparent`), HTTP API hygiene (RFC 9457 Problem Details, idempotency, pagination, ETag).

**Personal working preferences are not shipped with the suite.** A person may keep their own `working-style` skill in the CLI's user scope (`~/.copilot/skills/working-style/`) covering tone, how much to explain, how proactive to be, and how they phrase directives. If one is present it loads by description match like any other skill — honour it. If none exists, that is the normal case: fall back to the repository's own instructions and these standards. **Never author one on someone's behalf, and never assume a preference that isn't written down.**

## 4. Decision-record check (advisory)

**Many teams don't use ADRs at all — that is a legitimate choice, not a gap.** Establish first whether this project does:

- `documentation.adr.format: none`, **or** an empty `adr.location` with no ADR folder on disk → **the project does not use ADRs.** Skip the rest of this section. Do not create an `docs/adr/` folder, do not recommend adopting ADRs unasked, and do not treat "no ADR covers this" as a finding. Decisions get captured in the design doc's decision section (or the PR / work-item description) instead — see §5.
- Otherwise ADRs are in use; apply the checks below.

Before authoring code, IaC, tests, or design changes, check for accepted Architecture Decision Records:

- Look for `docs/adr/`, `docs/architecture/decisions/`, or `architecture/decisions/`. The profile field `documentation.adr.location` overrides this.
- Scan the index / filenames for ADRs relevant to the area you are touching.
- **Accepted ADRs are binding constraints** (chosen pattern, library, lifetime, layering rule). If your planned work would contradict one, **stop and surface the conflict** to the orchestrator (or user, if standalone) instead of silently diverging.
- Reference the ADR id in your hand-off when one applies.

**No agent authors an ADR on its own initiative.** ADRs are written up-front by humans. Every agent reads existing ADRs, honours them, and cites them, but never decides to create one mid-run — an undecided question is a **decision gap** to surface, not an ADR to write. `architect` may *draft a suggested body in chat* for a human to review. The one exception is an **explicit human request** to write an ADR, which the `architecture-decision-records` skill handles; it is never triggered by an autonomous run.

## 5. Decision capture (applies whether or not ADRs are used)

A decision that materially shapes the design needs its rationale captured **somewhere durable** — an accepted ADR, the declared framework's decision section (arc42 §9 by default), a design-doc note, or the work-item / PR description. **Any of these is valid.** Judge capture, not format: "there is no ADR for this" is only a finding in a project that uses ADRs.

When a materially-shaping decision has **no** capture anywhere, surface it as a **decision gap** (decision needed · why it matters · candidate options · recommendation) and let a human resolve it in whichever form the project uses. Never invent the decision silently.

## 6. Code localisation (on-demand, code-touching tasks only)

For changes that touch source code in a non-trivial-sized repository, also load the **`code-localisation`** skill. It returns a ranked list of relevant files using the backend chosen in `solution-profile.yaml: code_localisation.backend` (default `tree-sitter`).

Skip for: IaC-only changes, doc-only changes, single-file edits with an explicit path, repos under ~30 source files.

Pass the localisation result forward in your hand-off so downstream agents (reviewers in particular) don't re-run localisation.

## 7. Receiving a hand-off from another agent

When another agent hands you a structured block (`IMPLEMENTATION COMPLETE`,
`REVIEW COMPLETE`, `ARCHITECTURE DESIGN COMPLETE`, `INFRASTRUCTURE COMPLETE`, `TASKS PLANNED`,
or a Stage-1 brief from a supervisor):

- **Treat it as a contract.** If a required field is missing, ambiguous, or internally
  contradictory, **stop and surface** — name the missing field and what you would have done
  with it.
- **Do not infer or guess.** No "I'll assume the target was X." No filling in a default for a
  missing scope, target SHA, NFR, or constraint.
- **One corrective request, then stop.** Ask the upstream agent (or the supervisor) once for
  the missing field. If it comes back still malformed, stop with a clear note rather than
  retrying further.
- **Under a supervisor (`dev-lead`)**: a malformed hand-off fires the supervisor's
  stop-condition for malformed hand-offs — surface the gap, don't escalate further yourself.

This applies to **every agent**, authoring and read-only alike.

## 8. Improvements you notice along the way

A better approach, a conflict, or a missed dependency spotted mid-task is worth raising — but
**where** you raise it depends on how you were invoked:

- **Invoked directly by a person** — say so immediately, and act only on what was asked.
- **Under a supervisor (`dev-lead`)** — surface it to the supervisor for its Follow-ups list.
  **Never act on it in-run.** The supervisor's "never silently expand scope" rule wins.
- **Read-only review agents** put it in the review report's Follow-ups section. This includes
  suggested edits to skill files, which reviewers must never make themselves.

## 9. Verify before you assume

You are granted documentation tooling on every turn — `context7/*` for library / framework / SDK / API reference, `microsoft-docs/*` for Microsoft and Azure material, `web` for the rest, plus whatever vendor MCP servers the project registers. **Use it.** A grant no instruction exercises is capability the run carries and never gets.

**The rule.** When a fact would change what you write — an API signature, a default, a version-specific behaviour, a limit or quota, a deprecation, a config key, a resource schema — and you are **not certain** of it, look it up *before* writing, in Research and during implementation alike. Fast-moving APIs are precisely the class of fact recall is confidently wrong about, and a downstream gate is an expensive place to discover it.

**Cheapest authoritative source first:**

1. **This repo** — existing usage, lockfiles, the version actually installed. Free, and authoritative for *this* codebase: a library's current docs are not evidence about the version pinned here.
2. **The profile** — `tech_stack.*` names the versions the answer has to be true for.
3. **Documentation tooling** — `context7` / `microsoft-docs` / the vendor's own MCP server.
4. **`web`** — whatever the above don't cover.

**When you can't look it up.** Don't stall, and don't report a bare "documentation tooling unavailable" — from inside a session, *not installed* and *not granted* look identical, and the fix differs. Name both causes and their fixes: the server may be absent from the user's `mcp-config.json` (install / register it), or absent from this agent's `tools:` frontmatter grant (add it there). Then carry on and state the assumption in your hand-off — *"assumed `<fact>`; unverified — `context7` is either not registered in `mcp-config.json` or not granted in my `tools:`"* — so the next agent and the reviewers can challenge the fact *and* someone can repair the tooling. A labelled assumption is a known risk; an unlabelled one is a defect waiting to surface later.

**Cite what you checked** when a lookup shaped a non-trivial choice, the way you cite a profile field — source, and the version it applied to where that matters.

**Read-only agents included.** A lookup is a read. Reviewers should verify a claimed API contract, a cited limit, or a "that's the framework default" assertion rather than accept it — `reviewer-read-only-rules` bans writes, not reading documentation.

**Proportion.** This is not a mandate to research everything. Skip it for what the repo already settles, for stable language basics, and for reversible internal choices. Spend the lookup where being wrong is expensive: public contracts, persisted data, security posture, anything another team consumes.

## After loading this skill

The calling agent then:

1. States its role-tailored profile-field-honour list (which fields it depends on).
2. Loads any role-specific skills (e.g. `csharp-implementation`, `bicep-implementation`, `code-review-checklist`).
3. Applies its role-specific standards anchor (the "Apply engineering-standards to <role>" bullet list).
4. Begins the workflow.

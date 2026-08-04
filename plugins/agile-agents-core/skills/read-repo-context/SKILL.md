---
name: read-repo-context
description: Canonical preamble every coding-suite agent loads at the start of a turn. Reads `.github/copilot-instructions.md` and equivalents, loads `.github/solution-profile.yaml`, applies `working-style` + `trade-off-reporting`, and enforces the decision-record + decision-capture rules. Use as the first action in every coding, testing, infrastructure, architect, review, and reviewer agent. After loading, the agent applies its own role-tailored profile-field-honour list and conditional skills.
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

- If the file is missing, surface that to the orchestrator (or user, if standalone) and ask once whether to bootstrap from `solution-profile.yaml` or proceed without it.
- If a specific field you need is empty, ask the user once for that field — do not guess.
- Cite the profile field path (e.g. `solution-profile.yaml: tech_stack.test_discipline`) in your hand-off when it shaped a non-trivial choice.

## 3. Load shared user-scope skills

These four are loaded silently on every turn:

- **`working-style`** — enterprise standards (Clean Code, SOLID, DDD, Clean Architecture), security-by-default, collaboration patterns. Apply silently; do not echo it back.
- **`trade-off-reporting`** — at the end of your response, list non-obvious decisions with the rejected alternative, cost, and revisit trigger. Skip obvious / single-option choices.
- **`code-review`** — load when reviewing or auditing. Skip when implementing.
- **`cloud-native-patterns`** — load when the change involves an external boundary (HTTP / gRPC / message bus), shared resource (DB / cache / blob / queue), background work, startup / shutdown, or a new deployable. Canonical source for cloud design patterns, 12-Factor readiness, resilience defaults (Polly / `Microsoft.Extensions.Http.Resilience` / tenacity), observability (OpenTelemetry + W3C `traceparent`), HTTP API hygiene (RFC 9457 Problem Details, idempotency, pagination, ETag).

## 4. Decision-record check (advisory)

**Many teams don't use ADRs at all — that is a legitimate choice, not a gap.** Establish first whether this project does:

- `documentation.adr.format: none`, **or** an empty `adr.location` with no ADR folder on disk → **the project does not use ADRs.** Skip the rest of this section. Do not create an `docs/adr/` folder, do not recommend adopting ADRs unasked, and do not treat "no ADR covers this" as a finding. Decisions get captured in the design doc's decision section (or the PR / work-item description) instead — see §5.
- Otherwise ADRs are in use; apply the checks below.

Before authoring code, IaC, tests, or design changes, check for accepted Architecture Decision Records:

- Look for `docs/adr/`, `docs/architecture/decisions/`, or `architecture/decisions/`. The profile field `documentation.adr.location` overrides this.
- Scan the index / filenames for ADRs relevant to the area you are touching.
- **Accepted ADRs are binding constraints** (chosen pattern, library, lifetime, layering rule). If your planned work would contradict one, **stop and surface the conflict** to the orchestrator (or user, if standalone) instead of silently diverging.
- Reference the ADR id in your hand-off when one applies.

**No agent authors ADRs.** ADRs are written up-front by humans. Every agent reads existing ADRs, honours them, and cites them, but never creates one. `architect` may *draft a suggested body in chat* for a human to review and commit — it does not write the file.

## 5. Decision capture (applies whether or not ADRs are used)

A decision that materially shapes the design needs its rationale captured **somewhere durable** — an accepted ADR, the declared framework's decision section (arc42 §9 by default), a design-doc note, or the work-item / PR description. **Any of these is valid.** Judge capture, not format: "there is no ADR for this" is only a finding in a project that uses ADRs.

When a materially-shaping decision has **no** capture anywhere, surface it as a **decision gap** (decision needed · why it matters · candidate options · recommendation) and let a human resolve it in whichever form the project uses. Never invent the decision silently.

## 6. Code localisation (on-demand, code-touching tasks only)

For changes that touch source code in a non-trivial-sized repository, also load the **`code-localisation`** skill. It returns a ranked list of relevant files using the backend chosen in `solution-profile.yaml: code_localisation.backend` (default `tree-sitter`).

Skip for: IaC-only changes, doc-only changes, single-file edits with an explicit path, repos under ~30 source files.

Pass the localisation result forward in your hand-off so downstream agents (reviewers in particular) don't re-run localisation.

## After loading this skill

The calling agent then:

1. States its role-tailored profile-field-honour list (which fields it depends on).
2. Loads any role-specific skills (e.g. `csharp-implementation`, `bicep-implementation`, `code-review-checklist`).
3. Applies its role-specific standards anchor (the "Apply working-style to <role>" bullet list).
4. Begins the workflow.

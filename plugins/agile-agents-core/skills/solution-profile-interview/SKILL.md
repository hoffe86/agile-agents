---
name: solution-profile-interview
description: >-
  Bootstrap or repair `.github/solution-profile.yaml` by discovering what the repo already
  tells you and interviewing the human only for what it can't. Use when the profile is
  missing, when a required field is empty, when onboarding the agent suite into a new repo,
  or when the user asks to "set up the profile" / "run the interview". Used by
  `bootstrapper`; other agents may read it, but retain their role's write boundaries.
metadata:
  applies_to: all
---

# Solution Profile Interview

`solution-profile.yaml` has ~130 fields. Asking 130 questions is not an interview, it's an
interrogation, and the answers would be worse than what the repo already knows.

**Discover first, ask last.** Most fields are readable off the filesystem. Ask only for
decisions and facts that live in someone's head. Everything still unknown stays empty —
the template says *"Drop unknown / not-applicable optional fields. Don't fill in
placeholders."* An empty field is honest; a guessed one is a landmine.

## Procedure

### 1. Load what exists

Read `.github/solution-profile.yaml` if present. **Treat every non-empty value as
user-confirmed** and never re-ask it.

If absent, discover first, then **copy the template** in the approved write step — do not retype it. The template ships next to
this file at `<skill-dir>/references/solution-profile.template.yaml`, where `<skill-dir>` is
the directory of the `SKILL.md` you just loaded (you know that absolute path — it is how you
read this). Copy it to `.github/solution-profile.yaml` with a real file copy (`Copy-Item` /
`cp`), then edit values in place.

**Do not reproduce the profile from memory.** It has ~130 fields across 17 top-level
sections, and every field carries a comment listing its allowed values — those comments are
what you consult in step 4. A remembered version silently drops sections and invents key
names, producing a file the other agents cannot read. If the copy genuinely fails, stop and
report the path you tried rather than writing a substitute.

### 2. Discover (read-only)

Fill empty fields from filesystem signals — `references/discovery-signals.md` has the full
map. Do not run builds, install anything, or call the network.

First inventory native repo/path-scoped instructions, available local skills and
already-installed plugins using `read-repo-context` §1–3. Respect `applyTo` and
native scopes; do not flatten path instructions. Match descriptions/capabilities
and applicability, not a catalog or historical names. On-disk is not necessarily
available; distinguish absent from ungranted before proposing a gap.

Read existing CI/check scripts before deriving verification commands; a manifest
identifies a stack, not a runnable command. Record the source, working directory
and prerequisites in the proposal/solution guidance; populate existing
`quality_gates.test_bar.<check>.command` fields only when confirmed. An enabled
check without an evidenced command is a configuration gap, never a pass.
No guessed toolchain, new command schema or framework routing table.
Personal guidance is optional user-selected input, never a bootstrap requirement.

Record how each value was obtained; step 3 shows it back.

### 3. Ask — batched, and only for what step 2 couldn't answer

Present **one** consolidated draft with provenance markers:

- `✓` from the existing profile — shown for context, not up for discussion
- `🔍` auto-discovered — user confirms or corrects in-line
- `?` couldn't infer — needs an answer

Put the `?` block last and keep it short. These are the fields no repo scan can produce:

| Field | Why it can't be discovered |
|---|---|
| `identity.customer`, `identity.business_unit` | organisational, not in the code |
| `identity.lifecycle_stage` | a *decision*; tags only hint at it |
| `backlog.create_tasks`, `backlog.task_granularity` | how the team wants to work |
| `compliance_security.data_classification`, `regulatory_scope`, `data_residency` | contractual / legal |
| `operational.slo.*`, `on_call_contact` | agreed with the business |
| `engagement_context.*` | commercial context |
| `ai_copilot.*` | tenancy + governance policy |
| `cost_envelope.tier` | budget owner's call |
| `cost_envelope.model_tiers` | optional advisory model choices, not runtime policy |

If the user answers only some, that's fine — **do not chase optional fields**. Ask a focused
follow-up only for a still-empty **required** field (step 5).

**Interview etiquette:** one `ask_user` call for the whole draft, not one per field. Offer
concrete choices (from the template's comment on each field) rather than free text wherever
the field is an enum. Accept "skip" / "don't know" and move on.

### 4. Write

Present consequential configuration changes for explicit human approval before
persisting to `.github/solution-profile.yaml`. Update only changed fields; **preserve the
comments** — they are the field documentation and the only reason the file is readable.
Never reflow untouched lines.

Show the user a diff-style summary of what changed, not the whole file.

After each approved profile write, regenerate `AGENTS.md` with the bundled
[PowerShell](scripts/generate-agents-md.ps1) or [Bash](scripts/generate-agents-md.sh)
script; read [generation](references/generation.md) for invocation and safeguards.
Include this derived file in the approval; do not overwrite hand-maintained
instructions. Report a generator failure as incomplete bootstrap, not success.

### 5. Verify required fields

These six must be non-empty before the suite can run:

- `identity.project_name`
- `identity.lifecycle_stage`
- `documentation.location`
- `backlog.platform`
- `tech_stack.primary_languages` (≥ 1 entry)
- `tech_stack.test_discipline`

Any still empty → one focused follow-up question. **Do not silently proceed** and do not
invent a value to get past the check.

### 6. Optional native model setup

For model setup, first read **Manual native setup** and **Preference is not
governance** in [tier-defaults.md](../cost-budget/references/tier-defaults.md).
Propose only map-derived choices; the user approves and configures preferred
models manually in `/subagents`. Preserve explicit choices and per-agent overrides;
no map leaves settings untouched. Report unavailable choices, never substitute.
No user/global settings writes or profile-derived task model overrides.

## Guard rails

- **Never guess a compliance, security, or cost field.** A wrong `data_classification` or
  `regulatory_scope` is worse than an empty one — downstream agents act on it.
- **Discovery is read-only.** No builds, no installs, no network.
- **Don't fabricate the enums.** Every enumerated field lists its allowed values in the
  template comment; use exactly those.
- **Existing values win.** If discovery disagrees with a declared value, surface the
  conflict as a `🔍` line for the user to arbitrate — never overwrite silently.
- **Preserve the schema and six required fields.** Do not add a capability registry.
- **No automatic instruction edits or adoption.** Existing instructions belong to
  their repo/user owner; propose changes separately. Profile approval is not install
  approval, nor permission to relax harness gates or reviewer boundaries.

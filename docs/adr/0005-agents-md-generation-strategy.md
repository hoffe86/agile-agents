# ADR 0005 — `AGENTS.md` is generated from `solution-profile.yaml`, not hand-maintained

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H5)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H5); Stream E §"AGENTS.md Convergence"

## Context

`AGENTS.md` is converging as a cross-vendor convention (agents.md /
AgentSkills.io, Dec 2025) for "the prose file every coding agent reads
first". Claude Code, Copilot CLI, Cursor, and Aider are aligning on it.
Adopting it is necessary for portability — a customer who later switches
agents shouldn't lose their operational context.

But we already have a richer source of truth: `solution-profile.yaml`. It is
typed, schema-validatable, machine-readable, and explicitly separates
operational facts from narrative prose. Maintaining `AGENTS.md`
**by hand alongside** `solution-profile.yaml` would mean two sources of
truth that drift on every change.

The orientation of the two files is also different:

- `solution-profile.yaml` is the *operational* truth — the agents read it,
  validate against it, and gate behaviour on it.
- `AGENTS.md` is the *narrative summary* — what a foreign agent sees on
  first contact when it has no idea what `solution-profile.yaml` is.

## Decision

`AGENTS.md` is **generated** (not hand-written) from
`solution-profile.yaml` by a small generator skill. It
is regenerated on every meaningful profile change and committed to the
repo. The generated file carries a header banner stating it is generated
and pointing to `solution-profile.yaml` as the source of truth.

`solution-profile.yaml` remains the single source of truth. Drift is
prevented by construction: any field added to the profile schema gets a
generator template entry; the generator is run in CI so a stale `AGENTS.md`
fails the build.

Decisions feeding into this:

- **Reject** the "drop YAML, keep only `AGENTS.md`" path (research §C5):
  typed YAML is required for schema validation, downstream processing, and
  explicit separation of customer config from agent prose.
- **Reject** hand-maintaining `AGENTS.md`: drift is inevitable; the human
  cost of keeping two files in sync on every customer engagement is
  exactly the cost the agent suite is supposed to remove.

## Consequences

**Positive**
- Cross-vendor compatibility (Claude Code, Cursor, Aider, etc.) without
  giving up the typed profile our own agents need.
- Zero drift between operational truth and narrative summary — the
  generator is the only writer.
- Customer-project authors edit one file (the profile); `AGENTS.md` is
  derived.

**Negative**
- Generator is now a build dependency; if it breaks, `AGENTS.md` becomes
  stale.
- Foreign agents that *write* into `AGENTS.md` (some experimental tools do)
  would have their writes overwritten on next regeneration. Mitigation:
  the banner explicitly tells them not to.

## Alternatives considered

- **Hand-maintain `AGENTS.md`, drop `solution-profile.yaml`.** Rejected per
  research §C5 — loss of schema validation and downstream processing
  outweighs the simplicity gain.
- **Hand-maintain both.** Rejected: guaranteed drift; doubles authoring
  cost on every customer onboarding.
- **`AGENTS.md` as a thin pointer ("see solution-profile.yaml").**
  Rejected: defeats the point of the `AGENTS.md` convention, which is to
  be a self-contained narrative entry point.

## References

- `solution-profile.yaml` (the source of truth — every
  field becomes a generator template entry)
- `docs/research/autonomous-coding-agents-2026.md` §6 row H5; Stream E
  §"AGENTS.md Convergence"; §C5 (rejection of dropping YAML)
- AgentSkills.io / agents.md emerging convention (Dec 2025)

## Status update (adopted)

- **Date:** 2026-05-08
- **Status:** Adopted — implementation complete.

The strategy in this ADR is now in production for the template repo:

- A generated [`AGENTS.md`](../../AGENTS.md)
  is committed at the (simulated) repo root. It is auto-generated from
  `solution-profile.yaml` plus the per-agent / per-skill frontmatter and
  marked `<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->` at the top.
- A CI workflow,
  [`.github/workflows/agents-md-sync.yml`](../../.github/workflows/agents-md-sync.yml),
  regenerates `AGENTS.md` on every push / PR that touches
  `solution-profile.yaml`, any `*.agent.md`, any `SKILL.md`, or the
  generator scripts, and fails the build if the committed file drifts
  from its sources (`git diff --exit-code`). A `workflow_dispatch`
  trigger allows manual regeneration.
- `solution-profile.yaml` remains the **single source of truth** —
  `AGENTS.md` is a regenerated projection, never hand-edited.
- The convention is documented for downstream forks in
  [`docs/AGENTS-MD-MAPPING.md`](../../docs/AGENTS-MD-MAPPING.md).

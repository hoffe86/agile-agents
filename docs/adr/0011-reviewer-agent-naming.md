# ADR 0011 — Review agents take the `-reviewer` suffix; the orchestrator becomes `review-lead`

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (review-roster naming)
- **Related:** ADR 0010 (which created the sixth review agent and surfaced the collision), ADR 0006 (event-log `agent` enum), ADR 0007 (`model_tier` roster)

## Context

Two agents shared a name with two skills:

| Name | As an agent | As a skill |
|---|---|---|
| `code-review` | the general-quality lens (added by ADR 0010) | standalone whole-repository audit |
| `security-review` | the security lens | vendored awesome-copilot checklist |

The collision was tolerable while it was one name (`security-review`), and ADR 0010 knowingly
widened it to two, documenting it as unfixable. It is not unfixable — it is a naming problem —
and it has a concrete cost:

1. **It defeats the reference audit.** `audit-references.ps1` skips a backticked name that
   matches an agent, so that prose like "delegate to `test-reviewer`" is not read as a skill
   reference. A name that is *both* therefore can never be validated. Measured: deleting the
   entire `code-review` skill folder left the audit green, and the same held for
   `security-review`. Those were the only two skill references in the suite with no coverage.
2. **It is ambiguous to a reader.** "Do not load `code-review`" and "delegate to
   `code-review`" differ only by verb, and the agents had to spell out *which* `code-review`
   they meant in prose every time the two appeared together.
3. **No name-based rule can resolve it.** Once the skill is gone, the surviving reference is
   indistinguishable from an agent mentioned in prose. Any fix has to be a rename or a
   hardcoded invariant list.

## Decision

**Review agents take the `-reviewer` suffix. Skills keep `-review`.** An agent is an actor; a
skill is a process it performs.

| Old agent name | New agent name | Skill of the old name |
|---|---|---|
| `review` | **`review-lead`** | — |
| `code-review` | **`code-reviewer`** | `code-review` (unchanged) |
| `security-review` | **`security-reviewer`** | `security-review` (unchanged) |
| `test-review` | **`test-reviewer`** | — |
| `architecture-review` | **`architecture-reviewer`** | — |
| `infrastructure-review` | **`infrastructure-reviewer`** | — |

Supporting decisions:

- **All five lenses are renamed, not just the two that collided.** A roster reading
  `code-reviewer, security-reviewer, test-review, architecture-review, infrastructure-review`
  would be worse than either extreme: the suffix would carry no meaning, and the next person
  adding a lens would have no rule to follow.
- **The orchestrator becomes `review-lead`, not `reviewer`.** It supervises reviewers rather
  than being one, and the suite already has exactly this pattern in `dev-lead`. The chain
  reads `dev-lead → review-lead → *-reviewer`. Naming it `reviewer` would have made the one
  agent that performs no lens the hardest to tell apart from the five that do.
- **Skills are not renamed.** They are correctly named for what they are, they are the
  stable/vendored half (`security-review` mirrors its upstream awesome-copilot path), and
  renaming them would move the churn without removing it.
- **The marketplace keyword `code-review` stays.** It is a domain search term for humans, not
  an agent reference.

## Consequences

**Positive**
- The audit now validates both previously-unreachable skill references. Verified by deleting
  each skill folder in turn: the audit fails with a specific, correctly-attributed message,
  where before it passed green.
- `audit-references.ps1` drops a documented "known limit" and gains a "do not re-introduce
  this" warning in its place.
- Agent-vs-skill is legible from the name alone, so the disambiguating prose the agents
  carried can shrink to a one-line convention note.
- The convention gives future lenses an obvious name.

**Negative**
- **A breaking rename for anyone who references these agents by name** — a saved invocation,
  a script, or a downstream fork pinning `test-review` will not resolve. This is why it lands
  as a minor version bump with the rename table above.
- ~300 references across 47 files changed at once; the diff is large and mostly mechanical,
  which makes the few hand-edited lines easy to lose in review. Those were the lines where an
  agent and a skill of the same name appeared *together* — the "skill on this line" heuristic
  used for the bulk edit could not resolve them, and they were fixed individually.
- Historical documents (ADRs 0003–0010, `docs/research/`) keep the old names. They record
  decisions as taken at the time; rewriting them would falsify the record. This ADR's table is
  the mapping.

## Alternatives considered

- **Rename only the two colliding agents.** Rejected: leaves the suffix meaningless and gives
  the next contributor no rule.
- **Rename the two colliding *skills* instead** (e.g. `code-review` → `codebase-audit`).
  Defensible — arguably `codebase-audit` describes that skill better — but it moves churn onto
  the vendored half, breaks the mirror with the upstream awesome-copilot path for
  `security-review`, and leaves the agents named for a process rather than a role.
- **Keep the collision and add a hardcoded invariant** asserting both halves exist. Rejected:
  it protects the audit while leaving the ambiguity for every human reader, and the list would
  need hand-maintenance the script cannot prompt for.
- **`reviewer` for the orchestrator.** Rejected — see above.

## References

- `plugins/agile-agents-core/agents/*-reviewer.agent.md`, `review-lead.agent.md`
- `scripts/audit-references.ps1` (resolved-limit note; the collision warning that replaces it)
- `.github/copilot-instructions.md` § "Agent naming convention"
- ADR 0010 (created the sixth reviewer and recorded the collision as unfixable)

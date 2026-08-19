# Acceptance criteria — task-04

1. **File exists** at `docs/adr/0014-http-resilience-library.md`.
2. **Template followed** — the ADR uses the template defined by the
   `architecture-decision-records` skill (that skill is the single source of truth for
   ADR structure here; do not grade against a restatement of it).
3. **Supersede recorded in both directions** — the new ADR records that it replaces
   ADR-0007 with a working relative Markdown link, and the existing
   `docs/adr/0007-use-polly-for-resilience.md` is updated to point forward at ADR-0014.
   *Where* each of those goes is defined by the `architecture-decision-records` skill —
   grade the placement against the skill, not against any placement assumed here.
4. **Trade-off documented** — each of the three options has at least one paragraph stating
   what is gained and what is given up by picking it. Pure pros-and-cons bullet lists are
   acceptable but each con must include the *implication* (e.g., "tighter coupling to
   Microsoft release cadence ⇒ harder to back-port fixes").
5. **References cite primary sources** — at least two URLs from `learn.microsoft.com` or
   `github.com` for the chosen library; no blog posts as the sole source.

# Acceptance criteria — task-04

1. **Exact file scope** — add `docs/adr/0014-http-resilience-library.md` and update
   `docs/adr/0007-http-resilience-library.md`; no other working-copy files changed.
   The canonical sibling baseline remains unchanged.
2. **Template followed** — the new ADR follows the MADR template selected by the task
   profile's `documentation.adr.format` and defined by `architecture-decision-records`,
   including positive and negative consequences. Do not substitute Nygard or a custom
   six-section template.
3. **Bidirectional supersession** — the new ADR's **Links** explicitly says it supersedes
   ADR-0007 with a relative Markdown link. The working-copy predecessor's status is
   **superseded** with a relative Markdown link to ADR-0014; its historical rationale
   is preserved. Follow the skill's MADR lifecycle, not a custom Status section.
4. **Trade-off documented** — each of the three options has at least one paragraph stating
   what is gained and what is given up by picking it. Pure pros-and-cons bullet lists are
   acceptable but each con must include the *implication* (e.g., "tighter coupling to
   Microsoft release cadence ⇒ harder to back-port fixes").
5. **References cite primary sources** — at least two URLs from `learn.microsoft.com` or
   `github.com` for the chosen library; no blog posts as the sole source.

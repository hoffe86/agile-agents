---
name: backlog-item-standards
description: Tracker-agnostic content standards for authoring backlog work items — body structure per work-item type (Epic / Feature / PBI / Issue), writing rules, BDD/Gherkin scenario format, and the Definition of Ready checklist. Load when creating, improving, or reviewing a work item body. Pair with available solution-selected tracker guidance for field mapping and API shape. Used by backlog-manager.
metadata:
  applies_to: all
---

# backlog-item-standards

Two layers, loaded independently. The `backlog-manager` agent owns *when* to
author or revise an item and the autonomy rules around pushing it; this skill
owns *what a well-formed item looks like*, tracker-agnostically.

| Layer | Load when |
|---|---|
| [`references/work-item-content.md`](references/work-item-content.md) | Writing or reviewing the **body** of an item — structure per type, writing rules, BDD scenarios, Definition of Ready. |
| **Tracker-mechanics guidance** — select from available descriptions/capabilities via `read-repo-context`, including local skills and installed external plugins | Reading/writing tracker fields, linking, comments and sanitisation. Verify applicability to `backlog.platform` and the task; arbitrary names are valid. Without matching guidance, follow repo/tracker conventions and authoritative documentation and report the fallback. |

## Rules that apply to both

- **Structure is a floor, not a ceiling.** Every section in a template is
  expected; add level-specific elements where they apply. Omitting a section is a
  Definition-of-Ready gap and belongs in `## Open Points`, not silently dropped.
- **Never invent content to fill a section.** An unknown dependency, an
  unmeasured success metric, or an unconfirmed scope boundary is an open point —
  ask, don't fabricate.
- **Consistency is checkable:** every Key Objective maps to at least one
  Acceptance Criterion, and vice versa. A mismatch is a finding.
- **Nothing internal leaks to the tracker** — no draft paths, planning ids, or
  markdown comment blocks in field content. Users read those fields directly.

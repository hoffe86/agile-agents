---
name: backlog-item-standards
description: Tracker-agnostic content standards for authoring backlog work items — body structure per work-item type (Epic / Feature / PBI / Issue), writing rules, BDD/Gherkin scenario format, and the Definition of Ready checklist. Load when creating, improving, or reviewing a work item body. Pair with a tracker-mechanics skill (ado-work-items / github-issues) for field mapping and API shape. Used by backlog-manager.
applies_to: all
---

# backlog-item-standards

Two layers, loaded independently. The `backlog-manager` agent owns *when* to
author or revise an item and the autonomy rules around pushing it; this skill
owns *what a well-formed item looks like*, tracker-agnostically.

| Layer | Load when |
|---|---|
| [`references/work-item-content.md`](references/work-item-content.md) | Writing or reviewing the **body** of an item — structure per type, writing rules, BDD scenarios, Definition of Ready. |
| A **tracker-mechanics skill** — `ado-work-items` or `github-issues`, shipped in the matching `agile-agents-<tracker>` plugin | Reading from or writing to the tracker — field mapping, formatting, linking, comment templates, sanitisation. Match it to `solution-profile.yaml: backlog.platform`. If no such skill is installed, follow the tracker's own conventions and say so in the hand-off. |

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

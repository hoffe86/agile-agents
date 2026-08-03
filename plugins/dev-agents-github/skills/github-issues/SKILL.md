---
name: github-issues
description: GitHub Issues mechanics for reading and writing work items — tool entry points, the single-body field layout with section headings, cross-reference and closing-keyword syntax, labels / milestones / issue types / project fields, sub-issue parent-child hierarchy, comment templates, and content sanitisation. Load only when `solution-profile.yaml: backlog.system == github-issues`. Used by backlog-manager.
applies_to: github-issues
---

# github-issues

Tracker mechanics for **GitHub Issues**. The `backlog-manager` agent owns *when*
to author or revise an item and the autonomy rules around pushing it;
`backlog-item-standards` owns *what a well-formed item body looks like*; this
skill owns *which field it lands in and how the API call is shaped*.

Skip this skill entirely for any other tracker.

## Tooling

Issue operations go through the built-in GitHub tools: `issue_write`
(create / update), `issue_read` (get, comments, sub-issues, parent, labels),
`sub_issue_write` (add / remove / reprioritise children), `add_issue_comment`,
`list_issue_types`, and `list_issue_fields`. Read `backlog.url` from
`solution-profile.yaml` to resolve `owner` / `repo`.

If those tools are unavailable, say so and stop — do not fall back to shelling
out `gh` with an ad-hoc token, and do not silently switch to a different tracker.

## Field layout

GitHub has **one rich-text field** (`body`) — there is no separate Acceptance
Criteria field. Everything lives in the body under headings, in this order:

```markdown
## Goal
## Description
### Scope
### Out of Scope
## Key Objectives
## Acceptance Criteria
## External Dependencies
## Open Points
```

Consequences of the single-field model:

- Never split content across issues to emulate separate fields.
- `## Acceptance Criteria` as a task list (`- [ ]`) renders a progress bar on the
  issue and in the parent's sub-issue list — prefer it over plain bullets.
- Repro steps for a bug are a `## Repro Steps` heading inside the body, not a
  separate field.

**Structured metadata** — issue *types* (`list_issue_types`) and custom issue
*fields* (`list_issue_fields`) exist on some orgs. Discover what the repo
actually supports before setting them; never invent a type or field name. If the
repo has none, use labels.

## Formatting rules

- **Markdown everywhere.** GitHub renders the body and comments as GitHub-Flavored
  Markdown — no HTML variant to worry about.
- **Cross-reference** with `#123` in the same repo, `owner/repo#123` across repos.
  Do not paste full URLs; GitHub auto-links the short form.
- **Closing keywords** (`Closes #<n>`, `Fixes #<n>`) in a PR body auto-close the
  issue on merge. Use `backlog.pr_link_pattern` (conventionally `Closes #<n>`).
  Never put a closing keyword in an *issue* body — it would close the target when
  this issue's PR merges.
- **Mentions** (`@user`, `@org/team`) send notifications. Only mention when you
  need a specific person to act.

## Common fields

Take the values from `solution-profile.yaml` — never hardcode a project's vocabulary.

- **Labels** — GitHub's equivalent of ADO tags *and* area path. Read existing
  labels on sibling issues before applying; do not create new labels
  autonomously. Use `draft` (or the repo's equivalent) for items not yet refined.
- **Milestone** — the iteration / sprint equivalent. Maps to
  `backlog.default_iteration`. Assigning a milestone is iteration planning —
  human-owned; propose, don't apply unasked.
- **Assignees** — leave unset unless explicitly asked.
- **Severity** — GitHub has no severity field. Use labels
  (`severity:critical|high|medium|low`) if the repo already has them; otherwise
  state impact in the body and don't invent a label scheme.

## Hierarchy

GitHub models parent-child with **sub-issues**, not a parent field:

- Add a child with `sub_issue_write` (`method: add`, `sub_issue_id` = the child's
  **id**, not its number).
- There is no writable "parent" property — to re-parent, call `add` with
  `replace_parent: true`.
- Planned child tasks from a `dev-lead` Plan become **sub-issues of the parent
  story**. Create the issue first, then link it — a failed link leaves an
  unparented issue, so verify and report any that didn't attach.
- Sub-issues nest and carry a completion progress bar on the parent. Depth beyond
  two levels gets unreadable; prefer flat task lists under one story.
- **Dependencies** between issues are expressed in the body (`Blocked by #12`),
  not by a link type — GitHub has no predecessor/successor relation.

## Comments

**Voice:** professional, concise, factual. No emoji. Every comment either conveys
information or requests an action. Omit preambles, hedging, and filler. Reference
specific issue numbers, PR numbers, or milestones.

**Templates** (substitute `{{placeholders}}`):

| Purpose | Template |
|---------|----------|
| Status update | `**Status Update**: {{action_taken}}` + details |
| State change | `**State Change**: {{previous_state}} → {{new_state}}` + reason |
| Plan approach | `**Approach**: {{summary}}` + the per-task breakdown |
| Duplicate closure | `**Duplicate**: Closing as duplicate of #{{original_id}}.` — also set `state_reason: duplicate` and `duplicate_of` |
| Blocked | `**Blocked**: This issue is blocked by #{{blocker_id}}.` + context |
| Information needed | `**Information Needed**: {{specific_question}}` + why it's required |
| Milestone rollover | `**Milestone Rollover**: Moved from {{prev_milestone}} to {{new_milestone}}.` + reason |
| PR linked | `**PR Linked**: PR #{{pr_id}} (branch: {{branch}})` |

Closing an issue takes a `state_reason` — `completed`, `not_planned`, or
`duplicate`. Always set it; a bare close loses the why.

## Content sanitisation

Before any write, strip the following from all outbound body / comment content:

- Local file paths (e.g. `docs/draft-pbi-...md`, `.copilot-tracking/...`)
- Planning reference IDs or draft prefixes (e.g. `[DRAFT]`, `WI[NNN]`)
- Markdown comment blocks (`<!-- -->`) carrying internal notes

Issue bodies are public in a public repo and read directly by users — draft
artefacts must not leak into them.

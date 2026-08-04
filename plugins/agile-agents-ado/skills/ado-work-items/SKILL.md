---
name: ado-work-items
description: Azure DevOps Boards mechanics for reading and writing work items — MCP tool entry points, field mapping per work-item type (Epic / Feature / PBI / Issue / Task), markdown-vs-HTML formatting rules, cross-reference syntax, area path / iteration / tag conventions, severity scale, parent-child and predecessor linking, comment templates, and content sanitisation. Load only when `solution-profile.yaml: backlog.platform == ado-boards`. Used by backlog-manager.
applies_to: ado-boards
---

# ado-work-items

Tracker mechanics for **Azure DevOps Boards**. The `backlog-manager` agent owns
*when* to author or revise an item and the autonomy rules around pushing it;
`backlog-item-standards` owns *what a well-formed item body looks like*; this
skill owns *which field it lands in and how the API call is shaped*.

Skip this skill entirely for any other tracker.

## Tooling

Work-item operations go through the **Azure DevOps MCP server**
(`microsoft/azure-devops-mcp`). If those tools are not available in the session,
point the user at the setup block below and stop — do not fall back to raw REST
calls with a hand-rolled PAT, and do not silently switch to a different tracker.

The server is **not shipped with this plugin**: it takes the organisation as a
positional argument, and Copilot CLI does no `${input:}` / `${env:}` expansion in
MCP config, so a bundled config would hardcode someone else's org. Add it once to
`~/.copilot/mcp-config.json` (replace `contoso`):

```json
"ado": {
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@azure-devops/mcp", "contoso", "-d", "core", "work", "work-items"]
}
```

`-d core work work-items` keeps only the tools this skill uses; drop it for the
full Azure DevOps surface. Microsoft also offers a remote server —
`{"type":"http","url":"https://mcp.dev.azure.com/contoso"}` — which needs no
Node and is their recommended default.

Read `backlog.url`, `backlog.project`, `backlog.area_path`, and
`backlog.default_iteration` from `solution-profile.yaml` rather than asking for
them per call.

## Field mapping by work-item type

| Field | PBI / Feature / Epic / Task | Issue (bug) |
|-------|-----------------------------|-------------|
| Main content | `System.Description` | `Microsoft.VSTS.TCM.ReproSteps` + `System.Description` |
| Acceptance Criteria | `Microsoft.VSTS.Common.AcceptanceCriteria` | `Microsoft.VSTS.Common.AcceptanceCriteria` |
| Open Points | a custom readiness field, when the project defines one | same |
| Format | Markdown | Markdown |

**Custom fields are project-specific.** BDD scenarios and Open Points often live
in custom fields (e.g. `<Prefix>.GherkinBDDScenarios`,
`Custom.ReadinessandDonenessCriteria`). Discover the project's actual field
reference names before writing to them; if no custom field exists, fold the
content into `System.Description` under its own heading rather than inventing a
field.

## Formatting rules

- **Use markdown** for rich-text fields (Description, Acceptance Criteria, Open
  Points, BDD Scenarios) on **Azure DevOps Services**. Azure DevOps **Server**
  (on-prem) renders these fields as HTML — if the target is Server, emit the
  equivalent HTML structure instead. When unsure which platform is in use, ask once.
- **Cross-reference work items** using `#ItemId` syntax (e.g. `#419519`), not
  full ADO URLs — ADO renders these as clickable links automatically.
- **Include section headings** inside each field so items stay consistent:
  - `System.Description`: `## Goal`, `## Description`, `### Scope`,
    `### Out of Scope`, `## Key Objectives`, `## External Dependencies`
  - `Microsoft.VSTS.Common.AcceptanceCriteria`: `## Acceptance Criteria`
  - Open-points field: `## Open Points`

## Common fields

Take the values from `solution-profile.yaml` — never hardcode a customer's paths.

- **Area Path** — `backlog.area_path`. Ask once if unset; don't guess.
- **Iteration** — `backlog.default_iteration`. Match the project's existing depth
  exactly (`<Project>\Sprint <N>` and `<Project>\Iteration\Sprint <N>` are
  different paths; copying a sibling item's iteration is safer than composing one).
- **Tags** — the project's release / version tag plus `Draft` for items not yet
  refined. Read existing sibling items to learn the tag vocabulary in use.
- **Severity** (Issues / bugs only — `Microsoft.VSTS.Common.Severity`): set by
  impact, independent of Priority.
  - `1 - Critical`: system crash, data loss, or complete feature unavailability
  - `2 - High`: major feature broken with no workaround
  - `3 - Medium`: minor impact with a viable workaround
  - `4 - Low`: cosmetic or trivial issue

## Linking

- **Parent** links connect PBIs to Features, Features to Epics, Tasks to PBIs.
  Planned child tasks from a `dev-lead` Plan are always linked to their parent story.
- **Successor / predecessor** links express story dependencies — use these rather
  than encoding ordering in the description.
- **Related** links for non-blocking associations.
- Issues surface `Microsoft.VSTS.TCM.ReproSteps` as the primary visible field in
  the ADO UI — put the repro there, not only in the description.
- PR-to-work-item linking uses `backlog.pr_link_pattern` (conventionally `AB#<n>`).

## Work-item comments

**Voice:** professional, concise, factual. No emoji. Every comment either conveys
information or requests an action. Omit preambles, hedging, and filler. Reference
specific work-item IDs, PR numbers, or iteration paths.

**Templates** (substitute `{{placeholders}}`):

| Purpose | Template |
|---------|----------|
| Status update | `**Status Update**: {{action_taken}}` + details |
| State change | `**State Change**: {{previous_state}} → {{new_state}}` + reason |
| Plan approach | `**Approach**: {{summary}}` + the per-task breakdown |
| Duplicate closure | `**Duplicate**: Closing as duplicate of #{{original_id}}.` |
| Blocked | `**Blocked**: This item is blocked by #{{blocker_id}}.` + context |
| Information needed | `**Information Needed**: {{specific_question}}` + why it's required |
| Sprint rollover | `**Sprint Rollover**: Moved from {{prev_iteration}} to {{new_iteration}}.` + reason |
| PR linked | `**PR Linked**: PR #{{pr_id}} in {{repository}} (branch: {{branch}})` |

## Content sanitisation

Before any ADO write, strip the following from all outbound field content:

- Local file paths (e.g. `docs/draft-pbi-...md`, `.copilot-tracking/...`)
- Planning reference IDs or draft prefixes (e.g. `[DRAFT]`, `WI[NNN]`)
- Markdown comment blocks (`<!-- -->`) carrying internal notes

Users read ADO field content directly — draft artefacts must not leak into
work-item descriptions.

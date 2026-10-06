# Completion recipes

`dev-lead` owns the Done gate, write permissions, termination decisions and
event/cost semantics. This reference prepares evidence and report artifacts;
it does not grant permission or change a retry budget.

## Stage 9

### Requirement-coverage record

Each earlier gate compared a link to its predecessor — task ACs, repo commands,
or diff. Coverage reconciliation closes the loop to the original requirement.
Start with:

```sql
SELECT ac_id, text, covered_by, evidence, status FROM requirement_acs WHERE status = 'uncovered';
```

For **every** criterion, record its delivered task and evidence (test name or
review finding), not merely the task status. Also inspect previously covered
rows for tasks that ended blocked. An existing behaviour or another task's side
effect may legitimately satisfy a criterion: record what covers it rather than
inventing a task. Include `out-of-scope` rows and their reasons in the report.

Use the loaded skill's `references/done-report.md` for the report shape.
Consolidate stage trade-offs; carry assumptions and unapplied tracker transitions.
Set todo and tracker states only as authorised by the supervisor's coverage gate.

### Completion usage record

Collect completion usage using the loaded `cost-budget` skill's command with
persisted `run_started_at`, attribution log and applicable caps. Prepare its
unchanged JSON for `payload.cost_summary.usage`, with `collect-usage.py` as source
and the explicit measured / unmetered / unavailable / disabled status. The
supervisor determines the final outcome and non-empty termination reason for
partial or failed delivery; never fill missing usage with invented zeros.

### PR and release artifacts

Prepare the branch/commit/PR block even when opening the PR is awaiting approval:
branch from `backlog.branch_naming` (work-item id + slug), subject from
`backlog.commit_convention` + `required_commit_trailers`, and PR command.
Name an empty required profile field instead of inventing a convention.

Derive the PR command from **`identity.repo_url`, not the tracker**. Boards and
code may have different hosts:

- `dev.azure.com` / `*.visualstudio.com`: `az repos pr create`, needing the
  `azure-devops` CLI extension plus `--organization` / `--project` /
  `--repository` unless `az devops configure --defaults` is set.
- `github.com`: `gh pr create`.

Include `backlog.pr_link_pattern` (`AB#<n>`, `Closes #<n>`, etc.). Use
`pr-description` for the PR body, consuming hand-offs + diff and honouring
`.github/pull_request_template.md`; prepare the body file for the owning agent's
command. For a release identified by the human or profile cadence, use
`release-notes` for the CHANGELOG entry and release body over the relevant ref
range. Both skills compose with `conventional-commit` for subject parsing.

For a human-only operation, report the deliberate boundary (or pending approval)
and the exact command the human needs, not a fictitious missing tool/MCP server.

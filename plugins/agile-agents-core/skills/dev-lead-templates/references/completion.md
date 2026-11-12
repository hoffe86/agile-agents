# Completion recipes

`dev-lead` owns the Done gate, write permissions, termination decisions and
event/cost semantics. This reference prepares evidence and report artifacts;
it does not grant permission or change a retry budget.

## Stage 9

### Requirement-coverage record

Reconcile delivered evidence against the original requirement:

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

Resolve PR publication from **`identity.repo_url`, not the tracker**. Boards and
code may have different hosts. Use actually available, applicable solution
code-host guidance; otherwise return the prepared body for manual publication
and report the capability gap. Never guess a CLI or install an extension.

Include `backlog.pr_link_pattern`. Git safety and convention rules live in
`development-practices` §10; consuming these rules does not grant write authority.

**PR body:** read hand-offs, actual diff, CONTRIBUTING and the existing PR
template. Follow that template; otherwise use Summary, Why, Changes (by intent),
Risk and rollback, Test evidence, Breaking changes, Linked items, Reviewer
checklist. Record actual commands/results including failures/skips, measured
coverage or **not measured**, migration/consumer impact, and rollback limitations.
Do not invent intent, links or successful checks. Opening a PR requires explicit
approval for this run; preparing a body is not publication.

**Release notes:** only for a human request or profile cadence. Confirm the
explicit base/head ref range; do not guess tags or the default branch. Read its
log/diff and existing CHANGELOG/version/attribution conventions. Group user-facing
changes by intent; parse Conventional Commits only if selected by the profile.
Surface security fixes/advisories even when the subject omits them, and breaking
changes with concrete migration/upgrade steps. Include reversions and evidence
links; omit empty groups and unmeasured improvement claims. Return a ready-to-
prepend CHANGELOG section and optional release body; publishing requires caller
authority and an applicable capability, otherwise manual publication.

For a human-only operation, report the deliberate boundary (or pending approval)
and the exact command the human needs, not a fictitious missing tool/MCP server.

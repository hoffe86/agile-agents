# Implementation and review recipes

Read only the current stage's section. `dev-lead` retains all entry/exit gates,
delegation decisions, stops, retry counters and findings adjudication routing.
These are preparation and bookkeeping recipes, not alternate control flow.

## Stage 6

### Dependency-ready query and delegation payload

Select pending tasks whose dependencies are all `done`:

```sql
SELECT t.* FROM todos t
WHERE t.status = 'pending'
  AND NOT EXISTS (
    SELECT 1 FROM todo_deps td JOIN todos dep ON td.depends_on = dep.id
    WHERE td.todo_id = t.id AND dep.status != 'done');
```

Persist per-task hand-off facts in `todos.description` for context compaction.
Mirror the supervisor's neutral status transitions through the tracker recipe
only when task tracking applies.

Send **that task's** ACs and approach note, not the whole requirement as a work
assignment; otherwise the worker's scope and diff cannot be attributed to a
child item. Include the architect output (or requirement context if skipped),
explicit files / behaviours expected to change, in-scope / out-of-scope reminder
and Intake DoD. When architect ran, prepend:

> **Design constraints (locked by Stage 1):** <binding decision refs — ADR ids if the project uses ADRs>, chosen pattern <X>, allowed dependencies <list>. If you cannot deliver inside these constraints without a new dependency, boundary, contract, or cloud resource, **stop and report it** in your hand-off block — do not silently exceed scope.

For application work following analysis, include the analysis producer's
`Interface for coding` so the serving application follows the model's contract.

## Stage 7

### Gate invocation and evidence record

Use the loaded `test-bar-gate` skill's `scripts/run-gate.sh` (or `.ps1` on
Windows), after resolving `.github/solution-profile.yaml` with its documented
root-profile compatibility. Stack detection uses `tech_stack.primary_languages`
and `quality_gates.test_bar.<check>.command` overrides.

The smoke slot starts a runnable application and confirms it answers. An
ecosystem startup-discovery skill, if installed, supplies the entry point when
no `testing.smoke.command` is configured. A build alone cannot establish that
DI registration, connection strings or startup dependencies work.

Store the gate's commands, outcomes, explicit skips and content identity in the
session DB: verified HEAD, staged and unstaged diffs, and content hashes of
relevant untracked files, captured before **and** after verification. HEAD alone
cannot identify an uncommitted fix. The supervisor decides freshness and whether
applicable verification must run again.

For an applicable deploy check, load `deploy-verify` and follow its pipeline
verification recipe. Carry the structured failure report to the responsible
author unchanged; do not substitute a prose guess for the failing check.

## Stage 8

### Review payload

Provide `review-lead` the diff (`git diff <base>...HEAD`), original requirement,
per-task hand-offs, current Stage 7 content identity and gate results. Include
which checks ran, whether the host started or why it was `not_applicable` /
`undetermined`, and all `Existing tests modified` justifications.

`test-reviewer` cannot independently judge an assertion change on evidence it
never sees; an `undetermined` smoke result is a visible gap, not implied startup
success. For re-review include routed finding ids, fixer accounting, disputed
reasons and refreshed evidence supplied by the supervisor.

### Findings ledger SQL

Markdown is the exchange format; the session DB survives context compaction.
Track Critical and Major ids; Minor and Nits are report follow-ups.

```sql
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY,          -- C1, M2, … from the review report
  severity TEXT,                -- critical | major
  owner TEXT,                   -- coding | data-scientist | infrastructure | architect
  summary TEXT,
  status TEXT DEFAULT 'open',   -- open | fixed | disputed | accepted-risk
  note TEXT                     -- dispute reason, or the human's acceptance
);
```

Insert on first review; update accounting from each fixer's `Findings addressed`
lines. Query outstanding ids when preparing re-review:

```sql
SELECT id, owner FROM findings WHERE status = 'open';
```

Record a fixer's claim and evidence without treating the claim as closure;
`review-lead` adjudicates with its independent specialists. Only `dev-lead`
writes this ledger. Neither fixers nor reviewers share its session.

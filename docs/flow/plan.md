# Plan and approvals

## Decompose

`dev-lead` produces the smallest set of meaningful, independently implementable
tasks. Each task carries acceptance criteria and a short approach note, and every
requirement criterion maps to at least one task or is marked out of scope with a
reason. When you supply a `plan.md`, its decomposition is adopted and reconciled
rather than silently re-derived.

## Create tracker tasks

When `backlog.create_tasks` is true, `backlog-manager` creates one child work
item per task, linked to the parent, tagged `pending-approval`, and returns
`TASKS PLANNED`. A tracker-write failure stops the run before approval; it never
falls back to file-only planning silently.

## Plan approval

The **only mandatory approval gate**. It shows the tasks, assumptions, risks and
trade-offs, and offers:

- **Approve** — provisional tags are removed and autonomous execution begins.
- **Adjust** — tasks are revised and the plan is shown again.
- **Cancel** — provisional items from this run are cleaned up and the run stops.

A conditional **design approval** follows only when `architect` introduced a new
dependency, boundary or non-trivial trade-off, or reported a decision gap.

## When the run stops

After approval the run is autonomous, but it stops and asks you when it meets:

- ambiguity that changes what is delivered,
- a gate failure that survives its retry budget,
- a required scope change, destructive action or missing secret,
- a ❌ Block review verdict, or Major findings left open after review rounds,
- a malformed hand-off, an in-flight architecture escalation or a tracker failure,
- a request to open a pull request that you have not yet approved.

Resolvable details — naming, log levels, equivalent libraries — are decided,
labelled and reported instead.

Next: [Implement and quality gates](implement.md).

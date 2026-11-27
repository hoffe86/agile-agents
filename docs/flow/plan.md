# Plan and approvals

## Decompose

`dev-lead` produces the smallest set of meaningful, independently implementable
tasks. Each task carries acceptance criteria and a short approach note, and every
requirement criterion maps to at least one task or is marked out of scope with a
reason. When you supply a `plan.md`, its decomposition is adopted and reconciled
rather than silently re-derived.

## Refine

Before any tracker write, the same specialists review the draft in one parallel,
read-only refinement round: they agree with, change, split, merge or add tasks
and name how each task in their domain will be verified. `dev-lead` adopts or
declines each proposal. At approval you see every non-`none` `Dissent:`
verbatim and attributed, even if the lead thinks it has resolved the objection.
The lead gives its own reason for each declined proposal separately. Reviewers
do not help write the plan they will later check.

## Create tracker tasks

When `backlog.create_tasks` is true, `backlog-manager` creates one child work
item per task, linked to the parent, tagged `pending-approval`, and returns
`TASKS PLANNED`. A tracker-write failure stops the run before approval; it never
falls back to file-only planning silently.

## Plan approval

The **only mandatory approval gate**. It shows the tasks, assumptions, risks,
trade-offs, how each proposal was handled and every specialist's stated dissent.
It offers:

- **Approve** — provisional tags are removed where applicable. The lead checks
  whether separate design approval is required before any implementation
  write or implementation-agent dispatch. Provisional tracker writes may
  already have happened.
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

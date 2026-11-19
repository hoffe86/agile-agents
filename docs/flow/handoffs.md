# Hand-offs and tracker integration

## Canonical hand-off blocks

Delegated work ends with a fixed block. The names are a stable contract:

| Block | Producer |
|---|---|
| `BOOTSTRAP COMPLETE` | `bootstrapper` |
| `ARCHITECTURE DESIGN COMPLETE` | `architect` |
| `TASKS PLANNED` | `backlog-manager` |
| `IMPLEMENTATION COMPLETE` | `coding` — production code and its tests |
| `INFRASTRUCTURE COMPLETE` | `infrastructure` — IaC and its tests |
| `ANALYSIS COMPLETE` | `data-scientist` — an answer and its evidence |
| `REVIEW COMPLETE` | `review-lead` |
| `RESEARCH CONTRIBUTION COMPLETE` | `architect`, `coding`, `infrastructure`, `data-scientist` — read-only Research and Plan refinement input |

A missing or malformed block receives one corrective request; a second failure
stops the run. Field definitions live in the
[hand-off contracts](../../plugins/agile-agents-core/skills/read-repo-context/references/handoff-contracts.md).

## Tracker integration

The tracker is the source of truth for the plan. Only `backlog-manager` writes to
it, and the profile declares which tracker (`backlog.platform`, `backlog.url`).

Status uses a neutral vocabulary, mapped to your tracker's states:

| State | Set when |
|---|---|
| `in_progress` | Just before a task is dispatched |
| `implemented` | The task's gate passed; not yet verified against the requirement |
| `blocked` | A gate failed every retry, or a dependency is blocked |
| `done` | Only at completion, after requirement coverage is verified |

A failed status update warns and the run continues; a failed task *creation*
stops the run before approval.

## Run evidence

`dev-lead` alone emits structured events to `.copilot-runs/<run-id>/events.jsonl`
and collects measured usage with the cost-budget collector. Usage is never
self-reported, and USD is reported as unmetered when no rate is configured.

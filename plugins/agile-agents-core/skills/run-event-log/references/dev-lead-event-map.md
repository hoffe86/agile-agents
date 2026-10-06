# dev-lead event map

Supervisor-specific mapping from `dev-lead` pipeline transitions to canonical
`event_type` values. Semantics, required fields, and worked examples for each
type live in [`event-types.md`](event-types.md) — this file only says *when the
supervisor emits which*.

All events carry the `run_id` minted at Stage 0 and `agent=dev-lead` for events
the supervisor emits itself.

Cost attribution uses non-overlapping windows: supervisor work uses the stage
name; delegated work uses the worker role as `phase` (matching cost override
keys). Close the supervisor window before dispatch, open/close the worker
window around its work, then reopen supervisor work as needed. Repeated labels
aggregate within the same run, including corrective rounds. Only dev-lead emits.

| When | `event_type` | Required extras |
|---|---|---|
| Stage 0 start | `run_start` | `phase=intake`, `payload.requirement_summary`, `payload.profile_loaded` |
| Opening a work window | `phase_start` | `phase=<stage-name or worker-role>` |
| Closing that window | `phase_complete` | same `phase`, `outcome=success\|fail\|partial` |
| Dispatching a worker | `tool_call` | `tool_name=agent`, `args_summary="<agent-name>: <task one-liner>"` |
| Worker hand-off received | `handoff_received` | `payload.from_agent=<worker>`, `payload.sentinel=<block name>` |
| Worker malformed / failed | `error` | `error_kind=malformed_handoff\|build_fail\|...` |
| Test-bar / cost / review gate pass | `gate_check` | `payload.gate=test_bar\|cost\|review`, `outcome=success` |
| Test-bar / cost / review gate fail | `gate_check` | same, `outcome=fail`, `payload.reason` |
| Test-bar not applicable | `gate_check` | `payload.gate=test_bar`, `outcome=partial`, `payload.applicability=not_applicable`, non-empty `payload.reason` |
| Stage 9 normal close | `run_complete` | `outcome=success`, `payload.cost_summary` with collector provenance and measured/unmetered usage, or explicit unavailable/disabled state |
| Stop-condition abort | `run_complete` | `outcome=fail\|partial`, non-empty `payload.termination_reason`, and explicit cost-summary state |

`cost_summary` is a field in the terminal payload, not an event type. For
`measured` / `unmetered` results, copy the JSON from `collect-usage.py`
unchanged into `payload.cost_summary.usage` and set
`payload.cost_summary.source=collect-usage.py`. For a failed collection or a
disabled envelope, record the explicit status and reason; never substitute zero.

## Aliases

The `dev-lead` agent definition uses convenient shorthand (`stage.enter`,
`stage.exit`, `agent.dispatch`, `agent.complete`, `agent.fail`, `gate.pass`,
`gate.fail`, `run.abort`). These are **documentation names only** — on the wire,
emit the canonical `event_type` from the table above.

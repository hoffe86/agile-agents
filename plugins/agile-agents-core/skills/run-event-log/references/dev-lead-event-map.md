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
| Stage 0 start | `run_start` | `phase=intake`, `payload.requirement_summary` |
| Opening a work window | `phase_start` | `phase=<stage-name or worker-role>` |
| Closing that window | `phase_complete` | same `phase`, `outcome=success\|fail\|partial` |
| Dispatching a worker | `tool_call` | `tool_name=agent`, `args_summary="<agent-name>: <task one-liner>"` |
| Worker hand-off received | `handoff_received` | `payload.from_agent=<worker>`, `payload.sentinel=<block name>` |
| Worker malformed / failed | `error` | `error_kind=malformed_handoff\|build_fail\|...` |
| Test-bar / cost / review gate pass | `gate_check` | `payload.gate=test_bar\|cost\|review`, `outcome=success` |
| Test-bar / cost / review gate fail | `gate_check` | same, `outcome=fail`, `payload.reason` |
| Stage 9 normal close | `run_complete` | `outcome=success`; retain measured usage JSON per `cost-budget` (the legacy `cost_summary` event is unsupported) |
| Stop-condition abort | `run_complete` | `outcome=fail`, `payload.stop_condition=<n>` |

## Aliases

The `dev-lead` agent definition uses convenient shorthand (`stage.enter`,
`stage.exit`, `agent.dispatch`, `agent.complete`, `agent.fail`, `gate.pass`,
`gate.fail`, `run.abort`). These are **documentation names only** — on the wire,
emit the canonical `event_type` from the table above.

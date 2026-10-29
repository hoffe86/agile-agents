# Event types — narrative reference

The wire contract is [`event-schema.json`](event-schema.json). Every event is
written by **`dev-lead`**. A delegated worker is identified by its role window
(`phase=coding`, for example) and by `payload.from_agent` on
`handoff_received`—never by changing the event's `agent`.
The examples use schema version 2 and post-cutoff timestamps. Historical
unversioned logs remain archived as-is and do not count as current compliance.
The standalone `cost_summary` event shape shown in ADR 0006 is a historical
proposal, superseded by the approved v2 contract: cost data belongs in
`run_complete.payload.cost_summary`. ADR 0006 remains the accepted record for
the JSONL format and single-emitter decision; its historical example is not
the current wire schema.

Sentinel blocks remain the canonical hand-off. Events are additive and do not
replace them.

## `run_start`

First event in the file, after minting the run id and loading the profile.
Requires `payload.requirement_summary` (1–200 characters) and boolean
`payload.profile_loaded`; `outcome` is forbidden.

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:42:17.123Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "intake",
  "event_type": "run_start",
  "payload": {
    "requirement_summary": "Add a private storage module",
    "profile_loaded": true
  }
}
```

## `run_complete`

Last event. Requires `outcome` and `payload.cost_summary`; a `fail` or
`partial` outcome also requires `payload.termination_reason`.

The cost summary preserves the cost collector's result and provenance. Use:

- `status=measured` with `source=collect-usage.py` and the unmodified `usage`
  object when a USD rate was supplied.
- `status=unmetered` with the same source and usage object when measured
  tokens/AIU are available but `usage.usd` is `null` and
  `usage.usd_basis=not-metered`.
- `status=unavailable` with the source and a reason when collection failed.
- `status=disabled` with a reason when the profile disabled cost gating.

Do not manufacture zeroes or summarize values from memory. The collector's
`usage` JSON is the evidence; a null USD amount is not `$0.00`.

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:51:02.998Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "wrap-up",
  "event_type": "run_complete",
  "outcome": "fail",
  "payload": {
    "termination_reason": "A required verification gate did not pass",
    "cost_summary": {
      "status": "unavailable",
      "source": "collect-usage.py",
      "reason": "Usage store unavailable"
    }
  }
}
```

## `phase_start` and `phase_complete`

Emit both from `dev-lead` around one work window. The `phase` is the supervisor
stage or delegated role. **Windows never overlap**: close supervisor work before
dispatch, close each worker-role window before opening another, and reopen
supervisor work as needed. Repeated role windows are valid and aggregate in
cost attribution. `phase_start` forbids `outcome`; `phase_complete` requires
`success`, `fail`, or `partial`.

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:42:18.001Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "coding",
  "event_type": "phase_start"
}
```

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:46:30.111Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "coding",
  "event_type": "phase_complete",
  "outcome": "success"
}
```

## `tool_call`

Use for a non-trivial tool invocation. Requires `tool_name`; redact and cap
`args_summary` at 200 characters.

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:43:09.872Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "coding",
  "event_type": "tool_call",
  "tool_name": "agent",
  "args_summary": "coding: add the storage module and focused tests"
}
```

## `gate_check`

Requires `outcome` and `payload.gate`. Use stable gate names such as
`test_bar`, `cost`, and `review`. A test bar that truly does not apply uses
`outcome=partial`, `payload.applicability=not_applicable`, and a non-empty
`payload.reason`; do not call an unrun applicable check a skip.

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:47:00.000Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "test-bar",
  "event_type": "gate_check",
  "outcome": "partial",
  "payload": {
    "gate": "test_bar",
    "applicability": "not_applicable",
    "reason": "The change has no runnable application or tests"
  }
}
```

## `handoff_received`

Record a worker's completed hand-off without letting the worker emit an event.
Requires `payload.from_agent` and `payload.sentinel`.

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:46:31.000Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "coding",
  "event_type": "handoff_received",
  "payload": {
    "from_agent": "coding",
    "sentinel": "IMPLEMENTATION COMPLETE"
  }
}
```

## `error`

Record a caught failure with `error_kind` and a short, redacted
`payload.message` (1–200 characters). No other payload property is supported.
A gate failure is a `gate_check`, not an `error`.

```json
{
  "schema_version": 2,
  "timestamp": "2026-10-06T08:44:11.220Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "coding",
  "event_type": "error",
  "error_kind": "tool_timeout",
  "payload": {"message": "The delegated tool timed out"}
}
```

## Universal rules

- Timestamp each event in UTC with millisecond precision and the `Z` suffix.
- Keep `run_id` unchanged through the stream; `run_start` is first and
  `run_complete` is last.
- Never write top-level token or cost fields. Only a copied usage-collector
  result may provide measured cost data.
- Payloads and nested usage are closed allowlists; arbitrary summaries,
  transcripts, scorer responses, and extra properties are rejected.
- Do not log secrets, full file contents, or unredacted PII.
- Emitters and the trajectory checker reject common secret, email, and
  phone-like patterns, but this heuristic is not a comprehensive security
  boundary. Minimize and redact before emission.
- Keep the log append-only; the sentinel remains the canonical hand-off.

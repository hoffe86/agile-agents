# Event types — narrative reference

Companion to `event-schema.json`. For each `event_type`, lists when to emit, which fields are required beyond the five always-required ones (`timestamp`, `run_id`, `agent`, `phase`, `event_type`), which are recommended, and a worked example.

> **Reminder.** The event log is additive — every agent still prints its sentinel block (`IMPLEMENTATION COMPLETE`, etc.) for hand-off. JSON events are written **alongside**, not instead of.

---

## `run_start`

**Who:** `dev-lead` only.
**When:** First event in `events.jsonl`. Emit immediately after minting the run id and loading `solution-profile.yaml`.
**Required additional:** none.
**Recommended:** `payload.user_request_summary` (≤200 char), `payload.profile_loaded` (bool).
**Forbidden:** `outcome` (use `run_complete` to record outcome).

```json
{
  "timestamp": "2026-04-15T08:42:17.123Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "bootstrap",
  "event_type": "run_start",
  "payload": {
    "user_request_summary": "Add Bicep module for Storage Account with private endpoint",
    "profile_loaded": true
  }
}
```

**Common mistakes:** emitting `run_start` from a sub-agent (only `dev-lead` does this); forgetting that this MUST be the very first line of the file.

---

## `run_complete`

**Who:** `dev-lead` only.
**When:** Last event in `events.jsonl`, after every sub-agent has completed and the user-facing summary has been written.
**Required additional:** `outcome`.
**Recommended:** `duration_ms` (wall clock for the whole run). Token and cost totals are **not** carried here — they are measured by `cost-budget`'s `collect-usage.py`, not self-reported.

```json
{
  "timestamp": "2026-04-15T08:51:02.998Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "dev-lead",
  "phase": "wrap-up",
  "event_type": "run_complete",
  "outcome": "success",
  "duration_ms": 524000
}
```

**Common mistakes:** omitting `outcome`; double-counting tokens (this is the run total, not the sum of phase totals — sub-agent token counts are reported on each `phase_complete`).

---

## `phase_start`

**Who:** any agent.
**When:** First action after picking up work — before the first tool call of the phase.
**Required additional:** none.
**Recommended:** `parent_event_id` (the `handoff_received` or `phase_complete` that triggered this phase).
**Forbidden:** `outcome` (a phase that has only started has no outcome).

```json
{
  "timestamp": "2026-04-15T08:42:18.001Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "architect",
  "phase": "architecture",
  "event_type": "phase_start"
}
```

**Common mistakes:** emitting `phase_start` without a matching `phase_complete` (breaks duration calculations); emitting two `phase_start` events without a `phase_complete` in between (looks like overlapping phases to analysis tooling).

---

## `phase_complete`

**Who:** any agent.
**When:** Immediately before printing the sentinel block for hand-off.
**Required additional:** `outcome`.
**Recommended:** `duration_ms` (totals for this phase only), `parent_event_id` referencing the matching `phase_start`.

```json
{
  "timestamp": "2026-04-15T08:46:30.111Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "coding",
  "phase": "coding",
  "event_type": "phase_complete",
  "outcome": "success",
  "duration_ms": 184000
}
```

**Common mistakes:** forgetting `outcome`; emitting `phase_complete` and then continuing to do work in the same phase (close the phase **last**); using `outcome=success` when a quality gate failed (use `partial` or `fail`).

---

## `tool_call`

**Who:** any agent.
**When:** On any non-trivial tool invocation. "Non-trivial" = the call costs tokens, takes >1s, or mutates state. Skip cheap re-reads of files you already have in context.
**Required additional:** `tool_name`.
**Recommended:** `args_summary` (≤200 char redacted), `duration_ms`.

```json
{
  "timestamp": "2026-04-15T08:43:09.872Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "coding",
  "phase": "coding",
  "event_type": "tool_call",
  "tool_name": "edit",
  "args_summary": "infra/modules/storage.bicep — add privateEndpoint resource (lines 42-78)",
  "duration_ms": 2300
}
```

```json
{
  "timestamp": "2026-04-15T08:43:42.500Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "testing",
  "phase": "testing",
  "event_type": "tool_call",
  "tool_name": "powershell",
  "args_summary": "dotnet test src/Foo.Tests --logger trx",
  "duration_ms": 28400
}
```

**Common mistakes:** dumping the full tool arguments into `args_summary` (200 char cap is mandatory); logging secrets that appeared in arguments; logging every cheap `view` call (analysis becomes noise).

---

## `gate_check`

**Who:** reviewer agents (`review`, `security-review`, `architecture-review`, `infrastructure-review`, `test-review`) and `dev-lead` (when invoking `test-bar-gate`, lands in H3).
**When:** When a quality gate / checklist is evaluated.
**Required additional:** `outcome`.
**Recommended:** `payload.gate` (gate name), `payload.finding_count`, `payload.severity`.

```json
{
  "timestamp": "2026-04-15T08:46:55.410Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "security-review",
  "phase": "review",
  "event_type": "gate_check",
  "outcome": "fail",
  "payload": {
    "gate": "no-public-network-access",
    "finding_count": 1,
    "severity": "high"
  }
}
```

**Common mistakes:** using `outcome=success` for a gate that found issues but waived them (use `partial` and document the waiver in `payload`); forgetting that reviewer tool calls that mutate files are also `tool_call` events worth flagging (E3 spike depends on this).

---

## `handoff_received`

**Who:** any agent that picks up work from another agent.
**When:** Immediately on receiving the prompt — before `phase_start`.
**Required additional:** none.
**Recommended:** `parent_event_id` (the upstream `phase_complete`), `payload.from_agent`, `payload.sentinel` (which sentinel block triggered the hand-off).

```json
{
  "timestamp": "2026-04-15T08:46:31.000Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "review",
  "phase": "review",
  "event_type": "handoff_received",
  "payload": {
    "from_agent": "coding",
    "sentinel": "IMPLEMENTATION COMPLETE"
  }
}
```

**Common mistakes:** skipping this event (it's the only way to measure inter-agent latency); emitting it after `phase_start` (the order is `handoff_received` → `phase_start` → tool calls → `phase_complete`).

---

## `error`

**Who:** any agent that catches a recoverable failure.
**When:** Before retrying a failed tool call, before degrading to a fallback, or before emitting a `phase_complete` with `outcome=fail`.
**Required additional:** `error_kind`.
**Recommended:** `payload.message` (short human-readable; redacted), `payload.attempt` (retry counter).

```json
{
  "timestamp": "2026-04-15T08:44:11.220Z",
  "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
  "agent": "coding",
  "phase": "coding",
  "event_type": "error",
  "error_kind": "tool_timeout",
  "payload": {
    "message": "powershell call exceeded 120s, retrying with reduced scope",
    "attempt": 1
  }
}
```

**Common mistakes:** putting stack traces with file system paths or secrets into `payload.message`; using `error` for normal control-flow (e.g. a gate that returned `fail` is a `gate_check`, not an `error`); forgetting to follow up with either a successful retry event or a `phase_complete` with `outcome=fail`.

---

## Universal mistakes

- Forgetting `run_id` — events without it can't be correlated and are effectively garbage.
- Emitting JSON instead of JSON Lines (one event per line, no pretty-printing).
- Re-writing past events to "fix" mistakes — append-only. If you logged something sensitive, surface it in a trade-off note instead.
- Logging secrets, full file contents, or PII in `args_summary` / `payload`.
- Skipping the sentinel block because "the JSON event already says it's complete" — the sentinel stays canonical.

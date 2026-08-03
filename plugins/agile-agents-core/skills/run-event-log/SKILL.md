---
name: run-event-log
description: Emit one JSON Lines event per phase boundary, tool call, and completion to `.copilot-runs/<run-id>/events.jsonl` for audit, cost tracking, and post-hoc analysis. Loaded by every coding-suite agent. Sentinel blocks remain the canonical hand-off; the event log is additive structured telemetry.
applies_to: all
---

# run-event-log

Structured, append-only telemetry that runs **alongside** (never replaces) the sentinel-block hand-off (`IMPLEMENTATION COMPLETE`, `TESTS COMPLETE`, `INFRASTRUCTURE COMPLETE`, `ARCHITECTURE DESIGN COMPLETE`, `REVIEW COMPLETE`).

## Why this exists

Sentinel blocks are great for sync hand-off between agents, but they're prose — you can't query them. The event log gives us four things prose blocks can't:

1. **Audit trail** — replay any past run, attribute every action to an agent and phase
2. **Cost telemetry** — sum `tokens_in`, `tokens_out`, `cost_usd` per phase / agent / run; prerequisite to H4 cost discipline
3. **Reviewer-overlap analysis** — quantify how often `security-review` re-flags `code-review` findings; prerequisite to E3 spike on file-restriction enforcement
4. **Debugging** — when a run fails, the JSONL is the smallest reproducible record of what each agent decided to do

Citations: `docs/research/stream-e-blogs.md` §6 (Anthropic Managed Agents — every action a structured event), §25 (Sourcegraph mandates full transcripts).

## File layout

```
.copilot-runs/
└── <run-id>/                      # UUIDv7 minted by dev-lead at run start
    └── events.jsonl               # one JSON object per line, append-only
```

- One file per run. No rotation, no rewriting.
- `<run-id>` is a **UUIDv7** (time-ordered) minted once by `dev-lead` and propagated to every sub-agent via the hand-off prompt.
- Default base directory is `.copilot-runs/` relative to repo root. Override with `COPILOT_RUNS_DIR` env var.

## Event schema

The authoritative schema is `references/event-schema.json` (JSON Schema Draft 2020-12).
Narrative companion with examples per event type: `references/event-types.md`.

Every event has these required fields:

| field        | type    | notes                                                          |
| ------------ | ------- | -------------------------------------------------------------- |
| `timestamp`  | string  | ISO 8601 UTC, millisecond precision, `Z` suffix                |
| `run_id`     | string  | UUID minted by `dev-lead` at run start                         |
| `agent`      | enum    | `dev-lead` / `architect` / `coding` / `testing` / `infrastructure` / `review` / `security-review` / `architecture-review` / `infrastructure-review` / `test-review` |
| `phase`      | string  | free-form phase name (e.g. `architecture`, `coding`, `review`) |
| `event_type` | enum    | `run_start` / `run_complete` / `phase_start` / `phase_complete` / `tool_call` / `gate_check` / `handoff_received` / `error` |

Common optional fields: `correlation_id`, `parent_event_id`, `outcome`, `tokens_in`, `tokens_out`, `cost_usd`, `duration_ms`, `tool_name`, `args_summary`, `error_kind`, `payload`.

## What every coding-suite agent must emit

Three mandatory events per phase, plus N tool-call events:

1. **On phase entry** — `event_type=phase_start`. Mark the agent + phase you're starting. Useful for measuring time-in-phase.
2. **On any non-trivial tool call** — `event_type=tool_call` with `tool_name`, `args_summary` (≤200 char redacted summary), `tokens_in`, `tokens_out`, `cost_usd`, `duration_ms`. "Non-trivial" = anything that costs tokens, takes >1s, or mutates state. Skip cheap reads like `view` on a file you've already loaded.
3. **Just before the completion sentinel block** — `event_type=phase_complete` with `outcome=success|fail|partial`. The sentinel block stays exactly as it is — the JSON event is **additive**.

`dev-lead` additionally emits `run_start` (first event in the file) and `run_complete` (last event).

Reviewers also emit `gate_check` events when they pass / fail / waive a checklist gate. Receiving agents emit `handoff_received` when they pick up work from another agent.

On any caught failure, emit an `error` event with `error_kind` and a short `payload.message` before retrying or returning.

## How to emit

Use the helper scripts so you don't hand-craft JSON:

- PowerShell: `scripts/emit-event.ps1`
- bash: `scripts/emit-event.sh`

Both validate required fields per `event_type`, stamp `timestamp` with current UTC, append one JSON line to `${COPILOT_RUNS_DIR:-.copilot-runs}/<run-id>/events.jsonl`, and create the parent directory if missing.

Example (PowerShell, from a `coding` agent finishing a phase):

```powershell
.\scripts\emit-event.ps1 `
  -RunId  $env:COPILOT_RUN_ID `
  -Agent  coding `
  -Phase  coding `
  -EventType phase_complete `
  -Outcome success `
  -TokensIn 12450 -TokensOut 3120 -CostUsd 0.087 -DurationMs 184000
```

Example (bash, same event):

```bash
./scripts/emit-event.sh \
  --run-id "$COPILOT_RUN_ID" \
  --agent coding \
  --phase coding \
  --event-type phase_complete \
  --outcome success \
  --tokens-in 12450 --tokens-out 3120 --cost-usd 0.087 --duration-ms 184000
```

## Privacy & redaction rules

The event log will be reviewed by humans and may end up in audit packages. Therefore:

- **Never** log secrets, API keys, connection strings, tokens, or passwords. Not even in `args_summary` or `payload`.
- **Never** log full file contents. Use a path + line range or a 1-line summary.
- **Never** log PII (names, emails, project-confidential identifiers) unless the user explicitly requested it in `solution-profile.yaml`.
- For projects where `compliance_security.data_classification = restricted`, **hash file paths** (SHA-256, first 12 hex chars) before logging them in `args_summary` or `payload`. This preserves uniqueness for analysis without leaking project structure.
- `args_summary` is capped at 200 characters — truncate, don't omit.
- The event log is **append-only**. Never delete or rewrite past events. If you logged something sensitive by mistake, surface it to the user in a `## Trade-offs` block; do not try to scrub the file.

## Common mistakes to avoid

- Don't emit `phase_start` without a matching `phase_complete` — analysis tooling assumes pairs.
- Don't forget `run_id` — events without it can't be correlated and are effectively garbage.
- Don't log a `tool_call` for every micro-read — only for calls that cost tokens, take >1s, or mutate state.
- Don't try to "tidy" or rewrite the JSONL after the fact. Append-only.
- Don't replace the sentinel block — emit the JSON event **and** print the sentinel.

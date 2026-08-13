---
name: run-event-log
description: Emit one JSON Lines event per phase boundary, tool call, and completion to `.copilot-runs/<run-id>/events.jsonl` for audit, cost tracking, and post-hoc analysis. Loaded by every coding-suite agent. Sentinel blocks remain the canonical hand-off; the event log is additive structured telemetry.
applies_to: all
---

# run-event-log

Structured, append-only telemetry that runs **alongside** (never replaces) the sentinel-block hand-off (`IMPLEMENTATION COMPLETE`, `INFRASTRUCTURE COMPLETE`, `ARCHITECTURE DESIGN COMPLETE`, `REVIEW COMPLETE`).

## Why this exists

Sentinel blocks are great for sync hand-off between agents, but they're prose — you can't query them. The event log gives us four things prose blocks can't:

1. **Audit trail** — replay any past run, attribute every action to an agent and phase
2. **Cost telemetry** — the `phase_start` / `phase_complete` timestamps are the windows `cost-budget`'s `collect-usage.py` uses to attribute real, runtime-measured token usage per phase; prerequisite to H4 cost discipline
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
| `agent`      | enum    | `dev-lead` / `architect` / `coding` / `infrastructure` / `review` / `code-review` / `security-review` / `architecture-review` / `infrastructure-review` / `test-review` |
| `phase`      | string  | free-form phase name (e.g. `architecture`, `coding`, `review`) |
| `event_type` | enum    | `run_start` / `run_complete` / `phase_start` / `phase_complete` / `tool_call` / `gate_check` / `handoff_received` / `error` |

Common optional fields: `correlation_id`, `parent_event_id`, `outcome`, `duration_ms`, `tool_name`, `args_summary`, `error_kind`, `payload`. There are deliberately **no** token or cost fields — see below.

## Who emits what

**`dev-lead` emits everything.** It is the only agent that loads this skill, because it is
the only one that knows the phase structure — and because usage is attributed to a phase
by timestamp (see `cost-budget`), a worker emitting its own events would add nothing the
orchestrator's phase window does not already capture. An earlier version of this file told
every agent to emit; none did, and nothing depended on it.

1. **`run_start`** — first event in the file. **`run_complete`** — last.
2. **On phase entry / exit** — `phase_start`, then `phase_complete` with
   `outcome=success|fail|partial`. These two are load-bearing: they are the windows that
   attribute measured token usage to a phase, so a missing `phase_start` silently drops
   that phase's usage into `unattributed`.
3. **On a gate result** — `gate_check` with `outcome`, including the cost gate.
4. **On any caught failure** — `error` with `error_kind` and a short `payload.message`.

**Never write token or cost fields.** No agent can observe its own token consumption —
there is no tool, env var, or transcript field that exposes it — so any figure an agent
writes is invented. `collect-usage.py` reads the runtime's own metering instead.

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
  -DurationMs 184000
```

Example (bash, same event):

```bash
./scripts/emit-event.sh \
  --run-id "$COPILOT_RUN_ID" \
  --agent coding \
  --phase coding \
  --event-type phase_complete \
  --outcome success \
  --duration-ms 184000
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

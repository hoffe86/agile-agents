# ADR 0006 — Run-event-log schema: JSONL, OpenTelemetry-inspired event types, dev-lead-emitted

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H6)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H6); Stream E §6 (Anthropic Managed Agents), §25 (Sourcegraph transcripts)
- **Note (2026-08):** ADR 0009 removed the `testing` agent, ADR 0010 added a general-quality lens, and ADR 0011 renamed every review agent to the `-reviewer` suffix (`review` -> `review-lead`), so the schema's `agent` enum below is out of date as written. The schema decision — JSONL, OTel-inspired event types, dev-lead-emitted, no self-reported cost fields — is unchanged; `references/event-schema.json` carries the current enum.

## Context

Sentinel hand-off blocks (`IMPLEMENTATION COMPLETE`, `TESTS COMPLETE`, …)
are great for synchronous coordination but terrible for *audit*. They are
unstructured prose; they don't carry timing, cost, or gate outcomes; and
they are scattered across multiple LLM transcripts. Compliance asks
("what model produced this artefact, when, and at what cost?") cannot be
answered without grep gymnastics.

Anthropic's Managed Agents pattern (Stream E §6) and Sourcegraph's
mandate for full transcripts (§25) both point at the same primitive: a
structured event stream per run.

We need a format that:

- is line-appendable (no rewrite-on-update — survives crashes mid-run),
- is greppable, jq-able, and sql-loadable without a parser,
- is friendly to future OTel export (the semantic conventions for
  `gen_ai.*` and `code.*` attributes are converging),
- can be emitted from shell scripts on developer laptops without a
  collector daemon.

## Decision

**Format: JSONL** — one JSON object per line, append-only, written to
`.copilot-runs/<run-id>/events.jsonl`. The dev-lead mints `run_id`
(UUIDv7, time-orderable) at Stage 0 and propagates it to every sub-agent
via `COPILOT_RUN_ID` so all events for a run land in one file.

**Event types** (minimum set, defined in
`coding/skills/run-event-log/references/event-schema.json`):

- `run.start` / `run.complete` / `run.abort`
- `stage.enter` / `stage.exit`
- `agent.dispatch` / `agent.complete` / `agent.fail`
- `gate_check` (with `payload.gate = test_bar | cost | review` and
  `outcome = pass | fail | skipped`)
- `cost_summary` (final aggregate `{ total_usd, by_phase, by_agent }`)

Field naming follows OpenTelemetry semantic conventions where they exist
(`run_id`, `agent`, `phase`, `outcome`, `payload.*`) so a future OTel
exporter is a translator, not a rewrite.

**The dev-lead is the single emitter.** Workers don't write the JSONL
themselves — they signal completion via sentinel blocks (which the
dev-lead parses) and the dev-lead synthesises the corresponding events.
Reasons:

1. **Atomic ordering.** A single writer trivially produces a totally
   ordered stream; multi-writer JSONL needs locking or a collector.
2. **Worker portability.** Every worker would otherwise need access to
   the same shell scripts and the same `COPILOT_RUN_ID` resolution
   logic. Centralising removes that surface.
3. **Audit clarity.** The supervisor's view of "what happened" is the
   audit-grade narrative; worker-self-reported telemetry can lie or omit.
4. **No silent drift.** Adding an event type means editing one file
   (dev-lead) plus the schema, not 11 worker agents.

The skill ships a thin `emit-event.sh` / `emit-event.ps1` so the
dev-lead's shell hooks can append events without inline JSON
construction.

## Consequences

**Positive**
- One file per run, totally ordered, machine-readable.
- Audit answers ("what model, when, what cost, what gate result") are a
  one-liner `jq` away.
- On-ramp to OTel export: rename a few fields and pipe through an
  exporter — no schema rework.
- Cost-budget (ADR 0004), test-bar gate (ADR 0003), and review gates all
  surface as `gate_check` events with the same shape.

**Negative**
- Single writer means worker-internal events (e.g., per-tool-call timing
  inside a coding session) are not captured at this layer. Acceptable for
  audit; if we ever need it, sub-traces can be added without breaking
  the run-level schema.
- JSONL files grow unbounded over many runs. Mitigated by the per-run
  directory layout — old runs can be archived or pruned wholesale.

## Alternatives considered

- **Structured log per worker** (each agent writes its own file).
  Rejected: ordering across workers requires a merge step; correlating
  events needs joining on `run_id` *and* timestamps; the supervisor
  view becomes a derived artefact rather than the source of truth.
- **Single JSON document per run, rewritten on each event.** Rejected:
  not crash-safe; performance degrades with run length; not appendable
  from a shell hook.
- **OTel directly from day one.** Rejected: requires a collector
  endpoint to be useful, which is exactly the infra-zero constraint our
  laptop-first runs need to avoid. JSONL is the on-ramp; OTel export is
  a future translator.
- **SQLite per run.** Rejected: opaque without tooling; not greppable;
  binary diffs in PR review.

## References

- `agents/dev-lead.agent.md` (sole emitter;
  `run_id` minting; per-stage and per-gate emissions)
- `skills/run-event-log/` (schema +
  `emit-event.sh` / `.ps1`)
- `docs/research/autonomous-coding-agents-2026.md` §6 row H6; Stream E
  §6 (Anthropic Managed Agents event log), §25 (Sourcegraph mandates
  full transcripts)
- OpenTelemetry semantic conventions, especially the GenAI and code
  attribute groups

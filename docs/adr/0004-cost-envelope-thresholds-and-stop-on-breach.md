# ADR 0004 — Per-run cost envelope (USD / tokens; minutes informational) with `stop_on_breach: true` default

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H4)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H4); Stream E "Cost Economics"

## Context

Agent runs can silently burn through a customer's monthly LLM budget when a
loop fails to converge. The existing `operational.cost_band_eur_monthly`
field captures the **steady-state application** cost — what the *deployed
product* costs to run per month. It says nothing about what a *single agent
run* should be allowed to spend before it has to stop and ask.

These are two different cost questions:

- *App* cost is observed in production over weeks; bounded by traffic.
- *Run* cost is observed in a single end-to-end agent invocation; bounded by
  recursion depth, retry loops, and reviewer fan-out.

Stream E's cost analysis (15× chat-token cost in agent flows; Shopify's
fine-tune yielding 2.2× faster + 68% cheaper) makes clear that the dominant
cost variable is *uncontrolled* agent turns — exactly what a per-run
envelope catches.

## Decision

A new top-level `cost_envelope` block in
`solution-profile.yaml` (the `cost_envelope:` key), distinct from
`operational.cost_band_eur_monthly`. Measured cost caps are enforced per run;
minutes are retained as an informational planning value, not a hard deadline:

| Setting | Default (medium tier) | Purpose |
| --- | --- | --- |
| `max_usd_per_run` | 25.00 | Token spend on expensive models |
| `max_tokens_per_run` | 2,000,000 | High-volume cheap-model loops |
| `max_minutes_per_run` | 60 | Informational planning only; no deadline enforcement |

`tier: small | medium | large` selects a default palette per
`plugins/agile-agents-core/skills/cost-budget/references/tier-defaults.md` (small ≈ $5,
medium ≈ $25, large ≈ $100). Per-field overrides win over tier defaults.

**`stop_on_breach: true` is the default.** On a hard breach (≥ 10% over any
measured cost cap), the dev-lead writes the cost-stop report
(`plugins/agile-agents-core/skills/cost-budget/references/cost-stop-report.md`), emits
`run.abort` with `gate=cost`, and stops. The user must approve the overrun
or split scope into a follow-up — there is **no auto-retry** at the cost
gate.

The `cost-budget` skill checkpoints **after every stage transition** in the
dev-lead pipeline (Stage 0 loads the envelope; every subsequent stage exit
calls `sum-costs.sh`). This is wired as a cross-cutting concern, not an
extra stage.

### Why multiple measured caps

A cheap-model loop can blow tokens without blowing USD, so measured cost
caps complement one another. A stalled planner can consume wall-clock time
without spending tokens, but this cost gate does not detect that case.
Operation timeouts must be established separately; the minutes planning
value is not a watchdog.

### Why `stop_on_breach: true` by default

- Cost overruns on customer engagements are reputationally and contractually
  expensive. Defaults must be safe.
- The opposite default (warn-only) means a stuck loop happily continues —
  exactly the outer-loop failure that the envelope exists to prevent.
- Projects that genuinely want warn-only (internal experiments, harness
  runs) can flip the flag explicitly with the rationale captured in code
  review.

## Consequences

**Positive**
- A runaway run costs at most one envelope, never an entire monthly budget.
- The cost gate lands in the same JSONL stream (ADR 0006) as every other
  gate, making cost issues visible in the same audit trail.
- Tier defaults give a sane starting point; per-project tuning is one field.

**Negative**
- A genuinely large refactor that needs > envelope must be approved (or
  split). Friction by design.
- USD figures rely on the tenant rate-card; cross-currency conversion is
  not done — the envelope is in `currency: USD` (settable) at face value.

## Alternatives considered

- **Reuse `operational.cost_band_eur_monthly` for run gating.** Rejected:
  conflates the two cost questions; would either set per-run caps absurdly
  high (so they never fire) or absurdly low (so steady-state app cost
  doesn't fit).
- **Single USD cap, no tokens.** Rejected: misses the cheap-loop failure
  mode. Wall-clock stalls are not covered by the cost envelope.
- **`stop_on_breach: false` default (warn-only).** Rejected: defeats the
  purpose — defaults must be safe in customer projects.
- **Tier defaults baked into the skill, no `tier` field.** Rejected: the
  field makes the chosen tier explicit in the profile, which is grep-able
  in audits.

## Amendment (2026-08) - the cost unit changed, the decision did not

The measured-cost-caps decision stands. Two mechanics in it turned out to
be unimplementable as written and were replaced:

- **`sum-costs.sh` is gone.** It summed `cost_usd` fields that agents were
  asked to emit - but an agent cannot observe its own token consumption, so
  those fields were never populated and the gate silently reported $0.00 and
  passed. Replaced by `plugins/agile-agents-core/skills/cost-budget/scripts/collect-usage.py`, which
  reads the runtime's own usage store and attributes it to phases by
  timestamp window. Nothing is self-reported.
- **The USD caps are inert by default.** The runtime meters in AIU, and cache
  reads bill at a fraction of fresh input, so any flat per-token USD rate
  overstates a real run by roughly an order of magnitude. `max_aiu_per_run` /
  `max_aiu_per_phase` are now the enforced caps; `max_usd_*` applies only when
  `cost_envelope.usd_per_aiu` supplies an org rate, and an unrated run reports
  USD as *unmetered* rather than as zero.

`max_tokens_per_run` remains enforced. `max_minutes_per_run` retains its key
and value but is informational, not enforced.

### Correction (2026-10-15) — minutes are planning information

The earlier claim that minutes were enforceable was incorrect.
`collect-usage.py` gates tokens, AIU, and rated USD, with no minutes gate or
runtime watchdog. Its summed call `duration_ms` is not elapsed wall-clock
runtime: overlapping calls can double-count time, and idle time is absent.
Elapsed runtime instead measures the interval from run start to current/end
timestamp. Deployment polling needs an explicitly established operation
timeout; a missing bound must be reported and polling stopped, not inferred
from a remaining global minutes budget. Numeric cost caps, breach thresholds,
and `stop_on_breach` are unchanged.

## References

- `solution-profile.yaml` → `cost_envelope:` key
  and 103–106 (`operational.cost_band_eur_monthly` — the *steady-state app*
  band, intentionally distinct)
- `plugins/agile-agents-core/agents/dev-lead.agent.md` (Stage 0 envelope
  load, per-stage checkpoint, cost-breach handling)
- `plugins/agile-agents-core/skills/cost-budget/` (skill, tier-defaults
  palette, cost-stop report template)
- `docs/research/autonomous-coding-agents-2026.md` §6 row H4; Stream E
  "Cost Economics"

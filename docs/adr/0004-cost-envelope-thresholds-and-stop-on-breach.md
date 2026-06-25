# ADR 0004 — Per-run cost envelope (USD / tokens / minutes) with `stop_on_breach: true` default

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
`solution-profile.yaml` (lines 206–219), distinct from
`operational.cost_band_eur_monthly`. Three orthogonal hard caps are
enforced per run:

| Cap | Default (medium tier) | Catches |
| --- | --- | --- |
| `max_usd_per_run` | 25.00 | Token spend on expensive models |
| `max_tokens_per_run` | 2,000,000 | High-volume cheap-model loops |
| `max_minutes_per_run` | 60 | Stuck loops where token spend stays low |

`tier: small | medium | large` selects a default palette per
`coding/skills/cost-budget/references/tier-defaults.md` (small ≈ $5,
medium ≈ $25, large ≈ $100). Per-field overrides win over tier defaults.

**`stop_on_breach: true` is the default.** On a hard breach (≥ 10% over any
cap), the dev-lead writes the cost-stop report
(`coding/skills/cost-budget/references/cost-stop-report.md`), emits
`run.abort` with `gate=cost`, and stops. The user must approve the overrun
or split scope into a follow-up — there is **no auto-retry** at the cost
gate.

The `cost-budget` skill checkpoints **after every stage transition** in the
dev-lead pipeline (Stage 0 loads the envelope; every subsequent stage exit
calls `sum-costs.sh`). This is wired as a cross-cutting concern, not an
extra stage.

### Why three orthogonal caps

Any single cap has a known evasion: a cheap-model loop blows tokens without
blowing USD; a stuck planner blows wallclock without blowing tokens. All
three together catch the realistic failure modes.

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
- **Single USD cap, no tokens/minutes.** Rejected: misses the cheap-loop
  and the wallclock-stall failure modes.
- **`stop_on_breach: false` default (warn-only).** Rejected: defeats the
  purpose — defaults must be safe in customer projects.
- **Tier defaults baked into the skill, no `tier` field.** Rejected: the
  field makes the chosen tier explicit in the profile, which is grep-able
  in audits.

## References

- `solution-profile.yaml` lines 206–219 (`cost_envelope`)
  and 103–106 (`operational.cost_band_eur_monthly` — the *steady-state app*
  band, intentionally distinct)
- `agents/dev-lead.agent.md` (Stage 0 envelope
  load, per-stage checkpoint, cost-breach handling)
- `skills/cost-budget/` (skill, tier-defaults
  palette, cost-stop report template)
- `docs/research/autonomous-coding-agents-2026.md` §6 row H4; Stream E
  "Cost Economics"

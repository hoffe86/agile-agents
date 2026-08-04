---
name: cost-budget
description: >-
  Read the per-run / per-phase cost envelope from `solution-profile.yaml: cost_envelope`, gate run start (refuse if envelope is missing on production-tier engagements), checkpoint at every phase transition, and abort with a clear stop reason if the envelope is exceeded. Loaded by `dev-lead` at run start and at every stage transition. Reads cost data from the `run-event-log` JSONL stream.
applies_to: all
---

# cost-budget

## Why this skill exists

Multi-agent runs are **expensive** and prone to runaway loops. Two pieces of evidence shape the policy:

- **Anthropic / "How we built our multi-agent research system"** (stream-e-blogs.md, "Cost Economics"): a multi-agent chat consumes **~15× the tokens** of a single-agent baseline. A loop that nobody is watching can burn an entire monthly Foundry quota in a single afternoon.
- **Shopify §21 ("Roast" fine-tune)**: a focused, fine-tuned 32B model was **2.2× faster and 68% cheaper** than the frontier model on the same task — i.e. the right tier for the job matters more than always reaching for the biggest model.

Runaway loops (an agent re-prompting itself, a reviewer/author ping-pong, a stuck "fix-the-tests" cycle) are the **#1 production failure mode** of agentic systems in real-world deployments. This skill is the circuit-breaker.

## What it does

1. **Reads the envelope** from `solution-profile.yaml`:

   ```yaml
   cost_envelope:
     per_run_max_usd: 25.00
     per_phase_max_usd: 8.00
     per_phase_max_usd_overrides:
       architect: 4.00
       reviewer-architecture: 3.00
     model_tiers:           # optional — pin specific models per tier
       heavy: gpt-5.4
       mid:   gpt-5-mini
       light: gpt-4.1
   ```

2. **Gates run start** (called by `dev-lead` before the first author runs):
   - If `cost_envelope` is **missing** AND `engagement_context.engagement_type == external-project` → **halt** and ask the user to declare an envelope. Production external-project work without a budget is not allowed.
   - If `cost_envelope` is missing on `internal` / `experiment` / `template` engagements → **warn** ("⚠️ No cost_envelope set — run will not be cost-gated") and continue.
   - If `cost_envelope` is present → record the limits and continue.

3. **Checkpoints at every phase transition** (called by `dev-lead` between stages — e.g. architect → coding, coding → testing, testing → review):
   - Sum `cost_usd` from `.copilot-runs/<run-id>/events.jsonl` for events whose `phase` matches the just-finished phase (use `scripts/sum-costs.ps1` or `.sh`).
   - Compare to `per_phase_max_usd` (or the per-agent override).
   - **Soft warn** if ≥ 80% of the limit.
   - **Hard halt** if exceeded by ≥ 10% — emit the structured stop report from `references/cost-stop-report.md` and stop the run.

4. **Run completion**: write a final `cost_summary` event to the event log:

   ```json
   {"ts":"2026-04-12T14:03:00Z","type":"cost_summary","run_id":"...","total_usd":18.42,"by_phase":{"architect":2.10,"coding":9.80,"testing":3.55,"review":2.97},"by_agent":{...}}
   ```

## Model tiering convention

Every agent declares `model_tier: heavy | mid | light` in its frontmatter (introduced in Wave 2). The tier is **portable**; the actual model is provider-specific (see `references/tier-defaults.md`).

| Tier  | Used by                                                                 | Why                                                              |
|-------|-------------------------------------------------------------------------|------------------------------------------------------------------|
| heavy | `architect`, all reviewers (`review`, `architecture-review`, `security-review`, `test-review`, `infrastructure-review`) | Explainability and judgement matter more than speed; a bad architecture or missed security finding is catastrophic. |
| mid   | `coding`, `testing`, `infrastructure`, `backlog-manager`                | Day-to-day authoring on a clear spec — cost-quality sweet spot. |
| light | `dev-lead` orchestration loops, doc-only / release-notes tasks          | High call volume, low reasoning load — keep cheap.              |

### Override

A project can pin specific models via `cost_envelope.model_tiers{}` in `solution-profile.yaml` (e.g. mandate `claude-opus-4.7` for `heavy` for an EU-residency-only engagement). The skill respects the override; the agent frontmatter is the **fallback default**.

## Stop-report

When the envelope is exceeded, emit the markdown report defined in `references/cost-stop-report.md` and stop the run. Do not auto-retry. The user must explicitly:

1. Approve the overrun (and optionally raise the envelope), or
2. Split the scope into a smaller follow-up run.

## Helpers

- `scripts/sum-costs.ps1` (Windows) and `scripts/sum-costs.sh` (Linux/macOS) — read the event log and emit `{ total_usd, by_agent, by_phase }` JSON. Use the `-Threshold` flag for a non-zero exit when the limit is exceeded.

## Citations

- stream-e-blogs.md — "Cost Economics" (the 15× multi-agent overhead figure).
- Shopify §21 — "Roast" fine-tune (32B = 2.2× faster, 68% cheaper than frontier on a focused task).

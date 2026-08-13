---
name: cost-budget
description: >-
  Read the per-run / per-phase cost envelope from `solution-profile.yaml: cost_envelope`, gate run start (refuse if envelope is missing on production-tier engagements), checkpoint at every phase transition, and abort with a clear stop reason if the envelope is exceeded. Loaded by `dev-lead` at run start and at every stage transition. Reads real per-phase / per-agent token + AI-unit usage from the CLI's own usage store via `scripts/collect-usage.py` -- agents cannot observe their own token spend, so nothing is self-reported.
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
     max_tokens_per_run: 2000000     # enforceable — the store meters tokens exactly
     max_aiu_per_run: 30000          # enforceable — AIU is the runtime's own cost unit
     max_aiu_per_phase: 8000
     max_aiu_per_phase_overrides:
       architect: 4000
     usd_per_aiu:                    # optional rate card; leave EMPTY if you have none.
                                     # 0.00 is a rate, not an absence - it makes every
                                     # USD figure compute as 0.00 and pass silently.
     max_usd_per_run: 25.00          # inert until usd_per_aiu is set
     model_tiers:           # optional — pin specific models per tier
       heavy: gpt-5.4
       mid:   gpt-5-mini
       light: gpt-4.1
   ```

   **Gate on AIU or tokens, not USD.** The runtime meters AI units; currency is a rate-card
   conversion it does not perform. A USD cap with no `usd_per_aiu` is inert — report it as
   inert rather than as `0.00`, which is what let the old gate pass every run silently.

2. **Gates run start** (called by `dev-lead` before the first author runs):
   - If `cost_envelope.enabled` is **false** → ⚠️ warn ("cost gating disabled by profile") and skip every check below for the whole run. Record it in the final report so a run that was never gated cannot be mistaken for one that passed.
   - If `cost_envelope` is **missing** AND `engagement_context.engagement_type == external-project` → **halt** and ask the user to declare an envelope. Production external-project work without a budget is not allowed.
   - If `cost_envelope` is missing on `internal` / `experiment` / `template` engagements → **warn** ("⚠️ No cost_envelope set — run will not be cost-gated") and continue.
   - If `cost_envelope` is present → record the limits and continue.

3. **Checkpoints at every phase transition** (called by `dev-lead` between stages — e.g. architect → coding, coding → testing, testing → review):
   - Run `collect-usage.py` and read `by_phase[<phase>]`. Usage is attributed to a phase by
     timestamp, from the `phase_start` / `phase_complete` events `dev-lead` already emits — which
     is why worker agents report nothing themselves: the orchestrator is the only agent that knows
     the phase structure.

     **Pass the run-level caps as flags.** The script enforces them and exits `2` on breach; if you
     omit the flags it only reports, and a declared cap is never applied:

     ```
     python scripts/collect-usage.py \
       --event-log .copilot-runs/<run-id>/events.jsonl \
       --max-tokens <cost_envelope.max_tokens_per_run> \
       --max-aiu    <cost_envelope.max_aiu_per_run> \
       --max-usd    <cost_envelope.max_usd_per_run> \
       --usd-per-aiu <cost_envelope.usd_per_aiu>
     ```

     Omit any flag whose key is unset — never substitute a default. `--max-usd` without
     `--usd-per-aiu` cannot evaluate, so pass both or neither.
   - Compare `by_phase[<phase>]` to `max_aiu_per_phase` (or the per-agent override).
   - **Breach** = script exit `2`, or the per-phase figure exceeding its cap by ≥ 10%.
   - On breach, honour `stop_on_breach`:
     - `true` (default) → emit the structured stop report from `references/cost-stop-report.md` and **halt the run**.
     - `false` → emit the same report as a **warning**, record it in the final report, and continue. Warn-only is rare and deliberate; never silently downgrade a halt without this key set.

4. **Run completion**: run `collect-usage.py` once more without `--event-log` filtering — keeping the same cap flags, so a run that stayed under every per-phase cap but breached a run-level one is still caught — and write the result as a `cost_summary` event, so the JSONL stream is self-contained for replay:

   ```json
   {"ts":"2026-04-12T14:03:00Z","type":"cost_summary","run_id":"...","tokens_total":1284310,"aiu":18420.5,"usd":null,"usd_basis":"not-metered","by_phase":{"architect":{"aiu":2100.0},"coding":{"aiu":9800.4}},"by_agent":{}}
   ```

## Model tiering convention

Every agent declares `model_tier: heavy | mid | light` in its frontmatter (introduced in Wave 2). The tier is **portable**; the actual model is provider-specific (see `references/tier-defaults.md`).

| Tier  | Used by                                                                 | Why                                                              |
|-------|-------------------------------------------------------------------------|------------------------------------------------------------------|
| heavy | `architect`, all reviewers (`review`, `code-review`, `architecture-review`, `security-review`, `test-review`, `infrastructure-review`) | Explainability and judgement matter more than speed; a bad architecture or missed security finding is catastrophic. |
| mid   | `coding`, `infrastructure`, `backlog-manager`                          | Day-to-day authoring on a clear spec — cost-quality sweet spot. |
| light | `dev-lead` orchestration loops, doc-only / release-notes tasks          | High call volume, low reasoning load — keep cheap.              |

### Override

A project can pin specific models via `cost_envelope.model_tiers{}` in `solution-profile.yaml` (e.g. mandate `claude-opus-4.7` for `heavy` for an EU-residency-only engagement). The skill respects the override; the agent frontmatter is the **fallback default**.

## Stop-report

When the envelope is exceeded, emit the markdown report defined in `references/cost-stop-report.md` and stop the run. Do not auto-retry. The user must explicitly:

1. Approve the overrun (and optionally raise the envelope), or
2. Split the scope into a smaller follow-up run.

## Helpers

- `scripts/collect-usage.py` — reads the CLI's usage store read-only and emits
  `{ totals, by_phase, by_agent, usd, usd_basis, unattributed }`. Flags: `--event-log`
  (per-phase attribution), `--since`, `--usd-per-aiu`, `--max-tokens`, `--max-aiu`,
  `--max-usd`. Exit **2** on a threshold breach, **3** when usage is unavailable.

  **Exit 3 is a tooling failure, not a budget breach** — no `python3`, no store, or a
  schema the CLI changed under us. Warn, record `cost telemetry unavailable`, and let the
  run continue; halting a delivery run because a metering table moved is the wrong trade.
  It is a single Python file because reading SQLite needs no dependency there, while both
  PowerShell and bash would need one.

## Citations

- stream-e-blogs.md — "Cost Economics" (the 15× multi-agent overhead figure).
- Shopify §21 — "Roast" fine-tune (32B = 2.2× faster, 68% cheaper than frontier on a focused task).

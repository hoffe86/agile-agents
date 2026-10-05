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

3. **Checkpoint after each closed phase window**, before dispatching more work.
   Persist `run_started_at` from the Stage 0 `run_start` timestamp and pass it
   as `--since` on every call, including completion and resume. `--event-log`
   attributes usage; it does **not** filter out earlier session usage.

   **Phase identity:** supervisor-only windows use their stage name. Worker
   windows use the dispatched role (`architect`, `coding`, `infrastructure`,
   `data-scientist`, `review-lead`, etc.), so agent-name override keys resolve
   exactly. Only dev-lead emits; close a supervisor window before opening a
   worker window and reopen it afterward if needed. Never overlap windows.
   Repeated windows for a role, including corrections, accumulate in one bucket
   for this run; neither a retry nor resume resets its cap.
   Parallel review lenses share `review-lead`'s window. Individual lens overrides
   have no separate window: report them as unapplied, never claim enforcement.

   Resolve the closed window's cap from
   `max_aiu_per_phase_overrides[<phase>]`, otherwise `max_aiu_per_phase`.
   Pass run caps to run flags, and the resolved phase cap only to its own flag:

     ```
     python scripts/collect-usage.py \
       --event-log .copilot-runs/<run-id>/events.jsonl \
       --since <persisted-run-start-UTC> \
       --max-tokens <cost_envelope.max_tokens_per_run> \
       --max-aiu    <cost_envelope.max_aiu_per_run> \
       --max-usd    <cost_envelope.max_usd_per_run> \
       --usd-per-aiu <cost_envelope.usd_per_aiu> \
       --phase <closed-window-label> --max-phase-aiu <resolved-phase-cap>
     ```

   Omit unset caps; pass `--phase` and `--max-phase-aiu` together or neither.
   Pass `--max-usd` only with a rate. A zero cap is explicit, not unset.
   The collector uses unrounded usage: **warn at ≥80%; breach at ≥110%**
   for run and phase caps (ADR 0004). Zero usage under a zero cap is allowed;
   any positive usage breaches it. Read its `warnings` and `breaches` arrays.
   Missing phase windows, invalid timestamps/caps, or unusable telemetry exit
   **3**, never a zero-valued substitute. Gating without `--since` also exits 3.
   - **Breach** = script exit `2`.
   - On breach, honour `stop_on_breach`:
     - `true` (default) → emit the structured stop report from `references/cost-stop-report.md` and **halt the run**.
     - `false` → emit the same report as a **warning**, record it in the final report, and continue. Warn-only is rare and deliberate; never silently downgrade a halt without this key set.

4. **Run completion**: collect again with the **same `--since`, `--event-log`,
   and run caps**, plus the just-closed phase cap when set. Never widen the
   collection to the whole session or lose phase attribution. Fill the final
   report from this result. The legacy `cost_summary` event recipe is
   not accepted by the current event schema/emitter; retain the measured JSON
   as a run artifact rather than hand-writing an invalid event. Event-protocol
   reconciliation is separate work.

## Model tiering convention

Every agent declares `model_tier: heavy | mid | light` in its frontmatter (introduced in Wave 2). The tier is **portable**; the actual model is provider-specific (see `references/tier-defaults.md`).

| Tier  | Used by                                                                 | Why                                                              |
|-------|-------------------------------------------------------------------------|------------------------------------------------------------------|
| heavy | `architect`, `data-scientist`, all reviewers (`review-lead`, `code-reviewer`, `architecture-reviewer`, `security-reviewer`, `test-reviewer`, `data-reviewer`, `infrastructure-reviewer`) | Explainability and judgement matter more than speed; a bad architecture or missed security finding is catastrophic. |
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
  `{ totals, by_phase, by_agent, usd, usd_basis, unattributed, warnings, breaches }`.
  Flags: `--event-log`, `--since`, `--usd-per-aiu`, run caps `--max-tokens`,
  `--max-aiu`, `--max-usd`, and `--phase` / `--max-phase-aiu`. Exit **2** at
  110% of a cap, **3** for unavailable usage or invalid metering configuration.

  **Exit 3 is a tooling failure, not a budget breach** — no `python3`, no store, or a
  schema the CLI changed under us. Warn, record `cost telemetry unavailable`, and let the
  run continue; halting a delivery run because a metering table moved is the wrong trade.
  It is a single Python file because reading SQLite needs no dependency there, while both
  PowerShell and bash would need one.

## Citations

- stream-e-blogs.md — "Cost Economics" (the 15× multi-agent overhead figure).
- Shopify §21 — "Roast" fine-tune (32B = 2.2× faster, 68% cheaper than frontier on a focused task).
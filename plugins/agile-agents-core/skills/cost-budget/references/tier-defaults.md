# Model tier defaults (2026-Q2)

These are historical 2026-Q2 recommendations, not executable defaults or current
model-suitability evidence. Agents record advisory `metadata.model_tier` in Copilot
frontmatter; this does not define a cross-harness contract. Confirm availability,
policy approval, and suitability before deliberately configuring a runtime model.

| Tier  | Anthropic           | OpenAI / Azure OpenAI | Notes                                                                       |
|-------|---------------------|-----------------------|-----------------------------------------------------------------------------|
| heavy | claude-opus-4.7     | gpt-5.4               | Planning, architecture & reviewers — explainability premium, judgement-heavy work. |
| mid   | claude-sonnet-4.6   | gpt-5-mini            | Day-to-day authors (coding, testing, infrastructure) — cost-quality sweet spot. |
| light | claude-haiku-4.5    | gpt-4.1               | Mechanical loops and doc-only tasks, subject to task evidence; not planning. |

The current [ADR 0007](../../../../../docs/adr/0007-model-tier-convention.md)
assignment for `dev-lead` is `heavy`: planning/decomposition, acceptance coverage,
risk sequencing, and gate judgement require deep reasoning. The roster has 0 light,
4 mid, and 11 heavy agents; `light` remains supported. This advisory policy does not
select a runtime model or validate the dated model recommendations above.

> **Re-baseline quarterly.** Re-evaluate these dated picks when models or task evidence
> change. `solution-profile.yaml: cost_envelope.model_tiers{}` may record preferences,
> but no runtime code consumes that map. Actual selection uses runtime-native controls,
> including top-level `model` when configured. Neither these recommendations nor the
> annotation automatically enforces `ai_copilot.approved_models`.

Profile tier values may be ordered nonempty lists of model IDs or legacy single
strings. Order is advisory, not automatic fallback. Use only `heavy`, `mid`, and
`light`, with no duplicate model IDs; each listed ID must appear in the profile's
`ai_copilot.approved_models`. The marketplace's existing checker validates this
static consistency in its root profile and generic shipped template, not the
runtime's model choice. Project-specific preferences belong in the project's
profile, never in the shipped template or these historical recommendations.

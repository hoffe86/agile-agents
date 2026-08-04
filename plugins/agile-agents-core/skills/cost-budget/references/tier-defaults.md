# Model tier defaults (2026-Q2)

These are the recommended model picks per tier per provider. The **tier** is portable across the agent suite; the **model name** is provider-specific and should be confirmed against the available deployments in your project before a run.

| Tier  | Anthropic           | OpenAI / Azure OpenAI | Notes                                                                       |
|-------|---------------------|-----------------------|-----------------------------------------------------------------------------|
| heavy | claude-opus-4.7     | gpt-5.4               | Architecture & reviewers — explainability premium, judgement-heavy work.    |
| mid   | claude-sonnet-4.6   | gpt-5-mini            | Day-to-day authors (coding, testing, infrastructure) — cost-quality sweet spot. |
| light | claude-haiku-4.5    | gpt-4.1               | Orchestration loops and doc-only tasks — keep cheap, high call volume.      |

> **Re-baseline quarterly.** These recommendations reflect 2026-Q2 pricing, latency, and capability. Frontier and mid-tier models churn fast — a model that is "heavy" today may be "mid" in two quarters. Re-evaluate tier picks at least every quarter, and immediately when a new generation lands (e.g. a new Claude Opus or GPT-5 successor). Pin the chosen models in `solution-profile.yaml: cost_envelope.model_tiers{}` so the choice is explicit and auditable per engagement.

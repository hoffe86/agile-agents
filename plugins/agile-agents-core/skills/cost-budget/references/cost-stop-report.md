# Cost-envelope stop report (template)

Emitted by the `cost-budget` skill when a per-phase or per-run envelope is exceeded by ≥ 10%. The run is **halted**; nothing else runs until the user responds.

## Template

```markdown
## ❌ Cost envelope exceeded — run halted

**Run ID:** `<run-id>`
**Envelope breached:** `<per_phase | per_run>`  (`<phase-name>` if per_phase)
**Limit:**   $<limit_usd>
**Actual:**  $<actual_usd>
**Over by:** <percent_over>%  (threshold to halt: ≥ 10%)

### Breakdown (from `.copilot-runs/<run-id>/events.jsonl`)

| Phase          | Agent                  | Cost (USD) | Tokens in | Tokens out |
|----------------|------------------------|-----------:|----------:|-----------:|
| <phase>        | <agent>                | <usd>      | <in>      | <out>      |
| ...            | ...                    | ...        | ...       | ...        |
| **Total**      |                        | **<sum>**  |           |            |

### Recommended next action

Choose one and reply:

1. **Approve overrun** — accept the cost as-is and resume from the next stage.
2. **Raise envelope** — bump `cost_envelope.max_usd_per_phase` (or per-agent override / `max_usd_per_run`) in `solution-profile.yaml` and resume.
3. **Split scope** — abandon this run, narrow the input (e.g. one feature instead of three), and start a fresh run within the original envelope.

Do **not** auto-retry. The same prompt with the same agents is overwhelmingly likely to land in the same place.
```

## Worked example — coding-phase blowout

```markdown
## ❌ Cost envelope exceeded — run halted

**Run ID:** `2026-04-12-1403-acme-checkout`
**Envelope breached:** `per_phase`  (`coding`)
**Limit:**   $8.00
**Actual:**  $11.40
**Over by:** 42.5%  (threshold to halt: ≥ 10%)

### Breakdown (from `.copilot-runs/2026-04-12-1403-acme-checkout/events.jsonl`)

| Phase     | Agent              | Cost (USD) | Tokens in | Tokens out |
|-----------|--------------------|-----------:|----------:|-----------:|
| architect | architect          |       1.80 |    42,000 |     12,500 |
| coding    | coding             |       7.10 |   180,000 |     61,000 |
| coding    | reviewer-code      |       3.20 |    95,000 |     14,800 |
| coding    | coding (retry x2)  |       1.10 |    28,000 |      9,200 |
| **Total** |                    |  **13.20** |           |            |

> Note the two `coding` retries triggered by `reviewer-code` — this is the canonical author/reviewer ping-pong loop. The retry budget for `coding` should be capped (see `loop-budget` skill) and / or the reviewer findings batched.

### Recommended next action

Choose one and reply:

1. **Approve overrun** — accept $11.40 for this phase and continue to `testing`.
2. **Raise envelope** — bump `cost_envelope.max_usd_per_phase_overrides.coding` to `12.00` and resume.
3. **Split scope** — drop one of the three checkout flows from the brief and re-run.
```

# Cost-envelope stop report (template)

Emitted by the `cost-budget` skill when a per-phase or per-run envelope is exceeded by ≥ 10%. The run is **halted**; nothing else runs until the user responds.

Every number here comes from `collect-usage.py`, which reads the runtime's own usage store. Do **not** hand-fill any figure — an agent cannot observe its own consumption, so a hand-written number is a guess dressed as a measurement. If the collector exits 3 (telemetry unavailable) there is no breach to report: that is a tooling failure, and the run continues with a warning.

## Template

```markdown
## ❌ Cost envelope exceeded — run halted

**Run ID:** `<run-id>`
**Envelope breached:** `<per_phase | per_run>`  (`<phase-name>` if per_phase)
**Metric:** `<aiu | tokens>`
**Limit:**   <limit>
**Actual:**  <actual>
**Over by:** <percent_over>%  (threshold to halt: ≥ 10%)
**In USD:**  <usd, or "unmetered — no `cost_envelope.usd_per_aiu` rate set">

### Breakdown (measured, from the runtime usage store)

| Phase          | Agent                  |       AIU | Tokens in | Tokens out |
|----------------|------------------------|----------:|----------:|-----------:|
| <phase>        | <agent>                |     <aiu> |      <in> |      <out> |
| ...            | ...                    |       ... |       ... |        ... |
| **Total**      |                        | **<sum>** | **<sum>** |  **<sum>** |

### Recommended next action

Choose one and reply:

1. **Approve overrun** — accept the cost as-is and resume from the next stage.
2. **Raise envelope** — bump `cost_envelope.max_aiu_per_phase` (or its per-agent override / `max_aiu_per_run`) in `solution-profile.yaml` and resume.
3. **Split scope** — abandon this run, narrow the input (e.g. one feature instead of three), and start a fresh run within the original envelope.

Do **not** auto-retry. The same prompt with the same agents is overwhelmingly likely to land in the same place.
```

## Worked example — coding-phase blowout

```markdown
## ❌ Cost envelope exceeded — run halted

**Run ID:** `2026-04-12-1403-acme-checkout`
**Envelope breached:** `per_phase`  (`coding`)
**Metric:** `aiu`
**Limit:**   8,000
**Actual:**  11,400
**Over by:** 42.5%  (threshold to halt: ≥ 10%)
**In USD:**  unmetered — no `cost_envelope.usd_per_aiu` rate set

### Breakdown (measured, from the runtime usage store)

| Phase     | Agent              |        AIU | Tokens in | Tokens out |
|-----------|--------------------|-----------:|----------:|-----------:|
| architect | architect          |      1,800 |    42,000 |     12,500 |
| coding    | coding             |      7,100 |   180,000 |     61,000 |
| coding    | review             |      3,200 |    95,000 |     14,800 |
| coding    | coding (retry x2)  |      1,100 |    28,000 |      9,200 |
| **Total** |                    | **13,200** |**345,000**| **97,500** |

> Note the two `coding` retries triggered by `review` — this is the canonical author/reviewer ping-pong loop. The retry budget for `coding` should be capped and / or the reviewer findings batched.
>
> Note also how little of the input is fresh: most of it is cache reads, which bill at a fraction of new input. That is exactly why the gate is on AIU — a flat per-token rate would overstate this run by roughly an order of magnitude.

### Recommended next action

Choose one and reply:

1. **Approve overrun** — accept 11,400 AIU for this phase and continue to `testing`.
2. **Raise envelope** — bump `cost_envelope.max_aiu_per_phase_overrides.coding` to `12000` and resume.
3. **Split scope** — drop one of the three checkout flows from the brief and re-run.
```

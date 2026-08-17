# Baselines

Append-only log of harness runs. One row per `(suite, run-id)` pair. The harness writes a row
automatically; humans may add a `Notes` clarification afterwards.

| Run ID                              | Date       | Commit SHA | Suite              | Resolved | Partial | Failed | Notes                              |
|-------------------------------------|------------|------------|--------------------|----------|---------|--------|------------------------------------|
| `<first run pending>`               | YYYY-MM-DD | `0000000`  | `swe-bench-subset` |   0 / 25 |  0 / 25 | 0 / 25 | Will be filled by first eval run   |
| `<first run pending>`               | YYYY-MM-DD | `0000000`  | `custom-eval`      |   0 / 10 |  0 / 10 | 0 / 10 | Will be filled by first eval run   |

## How to read this

- **Resolved / Partial / Failed** are absolute counts; percentages are derived (resolved /
  total). See [`scoring-rubric.md`](./scoring-rubric.md) for definitions.
- **Commit SHA** is the SHA of the framework (this template repo) the harness ran against.
  Downstream forks should use their own commit SHA.
- **Notes** column should mention any non-default flags, suite changes (e.g., re-stratified
  SWE-bench subset), or reviewer-overridden scores.

## When to add a row

- After every nightly CI run of the harness (automated)
- After any manual run that informed a `H*` or `E*` plan-item decision (manual)
- Before/after pairs for a single change should be tagged in `Notes` (e.g., `pre-H1`, `post-H1`)
  so the delta is unambiguous.

---

# Skill-eval baselines (S-layer)

Separate table because the S-layer grades **skills as artifacts**, not runs — see
[ADR 0014](../docs/adr/0014-skill-evaluation-with-waza.md). Everything below is
zero-credit and deterministic, so it can be regenerated at will:

```powershell
./scripts/check-skill-tokens.ps1     # hygiene + coverage
./scripts/run-trigger-evals.ps1      # routing
```

| Date       | Commit    | Metric                                | Value      | Notes |
|------------|-----------|---------------------------------------|------------|-------|
| 2026-08-17 | `871ec16` | Skills with parseable frontmatter     | 76 / 76    | Was 73/76 — three skills had invalid YAML and were being silently dropped by the CLI |
| 2026-08-17 | `871ec16` | SKILL.md within token budget          | 61 / 61    | Against the ratchet in `.waza.yaml`, set at measured cost — not an endorsement of current sizes |
| 2026-08-17 | `871ec16` | Always-on context cost per agent turn | ~8,100 tok | `read-repo-context` + `engineering-standards` + `trade-off-reporting` + `engineering-judgement` |
| 2026-08-17 | `871ec16` | Skills with an eval suite             | 0 / 61     | Starting point |
| 2026-08-17 | `9c2e4b8` | Skills with an eval suite             | 6 / 61     | Routing pilot |
| 2026-08-17 | `9c2e4b8` | Routing accuracy (trigger heuristic)  | 17 / 18    | 1 missed trigger, 0 false triggers |

**The one miss:** `engineering-judgement` scores **0.46** (threshold 0.6) on its own core
case — *"the ticket doesn't say what should happen when the upload fails; should I stop and
ask, or make the sensible call?"*. Its description is written in abstract vocabulary that
shares few tokens with how the situation is actually phrased.

Two things not to do with that number. Do not raise a threshold to clear it, and do not
stuff keywords into the description — the threshold is Waza's uncalibrated default, and
editing prose to move a metric is exactly what `engineering-judgement` §7 forbids. This is
why the routing suite **reports** while the frontmatter and token checks **gate**.


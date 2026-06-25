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

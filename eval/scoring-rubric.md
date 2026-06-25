# Scoring rubric

This document defines how the harness (and human reviewers, where automation is not feasible)
score each task. Status values are deliberately limited to **three** so trends are readable in
`baselines.md`.

## Status values

| Status     | Symbol | Meaning                                                                       |
|------------|--------|-------------------------------------------------------------------------------|
| `resolved` | ✅     | Every acceptance criterion is met. Build green. Tests green.                  |
| `partial`  | 🟡     | At least one criterion is met; remaining failures are non-catastrophic.       |
| `failed`   | ❌     | No criterion met, or build broken, or test regression introduced.             |

A "non-catastrophic" failure is one where the produced artefact compiles, runs, and would not
be rejected outright in human code review — but doesn't fully meet the acceptance bar.

## SWE-bench scoring

For SWE-bench Verified tasks the rubric mirrors the upstream definition so our numbers stay
comparable to published baselines:

| Status     | Test outcome                                                                            |
|------------|-----------------------------------------------------------------------------------------|
| `resolved` | All `FAIL_TO_PASS` tests now pass **and** all `PASS_TO_PASS` tests still pass.          |
| `partial`  | Some `FAIL_TO_PASS` tests pass; no `PASS_TO_PASS` regression.                           |
| `failed`   | Patch doesn't apply, build broken, or any `PASS_TO_PASS` test regresses.                |

The harness reads the upstream `FAIL_TO_PASS` / `PASS_TO_PASS` lists from the
`princeton-nlp/SWE-bench_Verified` dataset row keyed by `instance_id`.

### Why this mirrors upstream

- "Resolved" matches the published metric on the SWE-bench leaderboard.
- "Partial" gives us a smoother signal across commits than the binary upstream metric — useful
  for spotting near-misses caused by minor agent regressions.
- "Failed" is a strict superset of upstream's not-resolved (we additionally flag build breaks
  and PASS_TO_PASS regressions explicitly).

## Custom task scoring

For each task in `custom-eval/tasks/task-NN-*/`:

1. Read `acceptance.md` — it contains 3-5 numbered criteria.
2. Run the task (or, for narrative deliverables like #08 threat-model, have a reviewer read
   the produced artefact).
3. Mark each criterion as `pass` / `fail`.
4. Apply the table:

| All criteria `pass`                                  | → `resolved` |
| At least one `pass` and no broken build/test         | → `partial`  |
| All criteria `fail` **or** build/tests broken        | → `failed`   |

### Per-task notes

- **task-04 (ADR)**, **task-05 (PR description)**, **task-08 (threat model)** — narrative
  deliverables. Scoring is by a human reviewer who checks the criteria. The harness logs the
  criteria checklist + the produced artefact path so the reviewer has everything in one file.
- **task-01, 02, 06, 07, 09, 10** — code-producing tasks. Acceptance criteria include
  build/test commands the harness runs automatically (where the synthetic profile permits).
- **task-03 (Bicep)** — `bicep build` validates syntax; `az deployment group what-if` is
  out of scope for the harness (would require an actual Azure subscription).

## Aggregate metrics

Per suite the harness computes and writes to `summary.json`:

```jsonc
{
  "suite": "custom-eval",
  "run_id": "20260415-093014-custom-eval",
  "total": 10,
  "resolved": 6,
  "partial": 3,
  "failed": 1,
  "resolved_pct": 60.0,
  "partial_pct": 30.0,
  "failed_pct": 10.0,
  "tasks": [
    { "id": "task-01-csharp-minimal-api-endpoint", "status": "resolved" }
    // ...
  ]
}
```

The same fields are appended as a row to `baselines.md`.

## Pass threshold (harness exit code)

`run-eval.ps1` / `run-eval.sh` exit `0` when `resolved_pct >= PassThreshold` (default `60`),
and `1` otherwise. Adopters can tighten or loosen this in their CI pipeline:

```powershell
./run-eval.ps1 -Suite custom-eval -PassThreshold 75
```

```bash
./run-eval.sh --suite custom-eval --pass-threshold 75
```

## Reviewer guidance — when in doubt

- **Bias toward `failed` over `partial`** if the build is broken. A non-compiling artefact
  is worse than nothing because it pollutes downstream metrics.
- **Bias toward `partial` over `resolved`** if any acceptance criterion is unverifiable.
  Don't credit the agent for criteria you couldn't check.
- **Add a `Notes` line** in `baselines.md` whenever you down-grade a borderline `resolved` to
  `partial` — keeps the trend honest across reviewers.

# `swe-bench-subset/` — 25-task stratified slice of SWE-bench Verified

## What this is

A **manifest only** (`tasks.json`) of 25 task IDs drawn from the public
[SWE-bench Verified](https://www.swebench.com/verified.html) dataset
([`princeton-nlp/SWE-bench_Verified`](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
on Hugging Face).

We do **not** vendor the actual SWE-bench data here, for two reasons:

1. **License** — SWE-bench Verified is distributed under the dataset's own terms; mirroring
   it inside this template would be redundant and would risk going stale.
2. **Size** — the full Verified set is ~500 instances with patches, test files, and Docker
   image references; embedding it would bloat every downstream fork.

This is retained benchmark data, not a runnable suite. There is no dataset fetch,
repository checkout or task-execution path. Future execution requires separately
approved work under [#22](https://github.com/hoffe86/agile-agents/issues/22).

## Selection criteria for the 25-task subset

Designed to be a fast smoke-test that still gives a representative signal:

1. **Repo diversity** — at least 6 distinct upstream repos so the result isn't dominated by one
   codebase's idioms. Current spread:
   - `astropy/astropy` (3 tasks)
   - `django/django` (4 tasks)
   - `sympy/sympy` (4 tasks)
   - `scikit-learn/scikit-learn` (3 tasks)
   - `matplotlib/matplotlib` (3 tasks)
   - `pytest-dev/pytest` (3 tasks)
   - `psf/requests` (2 tasks)
   - `pylint-dev/pylint` (3 tasks)
2. **Difficulty stratification** — roughly 1/3 in each of the three bands the SWE-bench team
   uses informally:
   - `easy` (≤ 15 min for human dev) — 9 tasks
   - `medium` (15-60 min) — 9 tasks
   - `hard` (> 60 min) — 7 tasks
3. **Determinism** — only tasks with stable, hermetic `FAIL_TO_PASS` test sets (no flaky
   network/time-dependent tests). All tasks here are present in the public Verified subset
   and have been confirmed to be deterministic by the SWE-bench Verified curation team.
4. **Bounded size** — 25 selected instances keep the intended benchmark smaller
   than the full dataset. This manifest establishes no measured runtime.

## `tasks.json` schema

```jsonc
[
  {
    "instance_id": "django__django-15347",   // upstream SWE-bench Verified instance ID
    "repo": "django/django",                  // upstream repo (org/name)
    "difficulty": "easy"                      // easy | medium | hard
  }
  // ...
]
```

`instance_id` and `repo` identify the intended upstream input. `difficulty` is
selection metadata, not a runtime qualification.

## Scoring (SWE-bench-specific)

The upstream outcome definitions, for a future verified execution, are:

- **resolved** — all `PASS_TO_PASS` and `FAIL_TO_PASS` tests pass against the patch produced
  by `dev-lead` (this is the SWE-bench Verified definition of "resolved").
- **partial** — some `FAIL_TO_PASS` tests pass and no previously passing test regresses.
- **failed** — patch doesn't apply, build breaks, or `PASS_TO_PASS` regresses.

See [`../scoring-rubric.md`](../scoring-rubric.md#swe-bench). The active
[DeepEval scorer](../../deepeval/README.md) measures recorded skill invocation,
not SWE-bench outcomes.

## How to refresh / re-stratify

1. Pull the latest Verified manifest from
   [`princeton-nlp/SWE-bench_Verified`](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified).
2. Re-stratify by `difficulty` (the dataset includes a `difficulty` field).
3. Re-pick 25 instances meeting the criteria above; keep at least 50% overlap with the previous
   subset so cross-run trend lines stay comparable.
4. Note the swap in `baselines.md` (column: `Notes`) so historical comparison is honest.

## Portability

A downstream fork can replace this folder wholesale with their own `tasks.json` pointing at:

- A slice of their internal bug-tracker (each "instance" is one bug + its repro test)
- A coding-interview task bank
- A regression suite from a previous release

The manifest identifies inputs only; a fetch/execution implementation is not supplied.

## References

- SWE-bench Verified landing page: <https://www.swebench.com/verified.html>
- Hugging Face dataset: <https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified>
- Original SWE-bench paper: Jimenez et al., "SWE-bench: Can Language Models Resolve Real-World
  GitHub Issues?", ICLR 2024

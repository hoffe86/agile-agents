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

To actually run a SWE-bench task, the harness (or an adopter's wrapper around it) loads the
upstream instance by `instance_id` from the Hugging Face dataset at runtime.

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
4. **Manageable wall-clock** — 25 tasks runs in ~1-2 hours on a single agent run, fast enough
   for nightly CI but large enough for a meaningful signal.

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

The harness only requires `instance_id` and `repo`. `difficulty` is metadata used in
`baselines.md` for stratified reporting.

## Scoring (SWE-bench-specific)

A task is scored:

- **resolved** — all `PASS_TO_PASS` and `FAIL_TO_PASS` tests pass against the patch produced
  by `dev-lead` (this is the SWE-bench Verified definition of "resolved").
- **partial** — some `FAIL_TO_PASS` tests pass and no previously passing test regresses.
- **failed** — patch doesn't apply, build breaks, or `PASS_TO_PASS` regresses.

See [`../scoring-rubric.md`](../scoring-rubric.md) §SWE-bench for the long form.

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

The only contract is the `instance_id` + `repo` pair plus a way for the harness to fetch the
problem statement and tests at runtime.

## References

- SWE-bench Verified landing page: <https://www.swebench.com/verified.html>
- Hugging Face dataset: <https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified>
- Original SWE-bench paper: Jimenez et al., "SWE-bench: Can Language Models Resolve Real-World
  GitHub Issues?", ICLR 2024

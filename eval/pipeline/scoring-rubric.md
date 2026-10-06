# Scoring rubric

Outcome evidence and harness execution status are distinct. The contract shared by the
native shell judge and DeepEval is [`../grading.py`](../grading.py); judge doctrine is
[`acceptance-grading`](../../plugins/agile-agents-core/skills/acceptance-grading/SKILL.md).

## Status and exit policy

| Task status | Meaning | Scorer exit |
|---|---|---:|
| `resolved` | Every actual acceptance criterion verified PASS | 0 |
| `failed` | Verified failures with no passes, or proven catastrophic breakage | 1 |
| `partial` | Fully verified; some PASS, non-catastrophic FAIL | 2 |
| `unverified` | Uncertainty prevents a verified outcome; never resolved credit | 3 |
| `setup_error` | Fixture/setup, judge CLI/environment/timeout, or malformed judge contract | 4 |
| `blocked_approval` | Mandatory human plan approval cannot be received unattended | n/a |
| `skipped` | Dry run: neither agent nor judge executed | n/a |

The **prepare CLI** uses exit **2 for setup_error**, not partial. The **suite runners**
use 2 for setup_error, 3 for unverified or blocked_approval, 0 for a dry-run wiring check,
and otherwise 0/1 according to the resolved threshold. The JSON status disambiguates
these interfaces. Threshold 0 cannot turn an unverified or setup-error run into success.

## Per-criterion contract

Read the actual numbered list in `acceptance.md` (not a hardcoded criterion count).
Require exactly one anchored `N. PASS - evidence`, `N. FAIL - evidence`, or
`N. UNVERIFIED - reason` line per criterion, and exactly one final anchored
`VERDICT: RESOLVED|PARTIAL|FAILED|UNVERIFIED` line. Matching is case-insensitive.
Status words in prose do not count. Missing/malformed/duplicate lines are judge-contract
errors. A nonzero judge CLI exit invalidates credit even if its stdout claims RESOLVED.

The claimed verdict is retained separately from normalization. PASS+FAIL cannot resolve.
PASS+UNVERIFIED and PASS+FAIL+UNVERIFIED normalize to unverified (score 0); all-unverified
is explicitly unverified. FAIL+UNVERIFIED without any PASS remains failed, retaining
uncertainty and every verified failure. Missing tools are not failures of produced work.
`AcceptanceMetric.success` is false for every uncertain/error result even at threshold 0.

Results contain `claimed_verdict`, `normalized_verdict`, `criteria` with reasons,
`verified_failures`, `complete` (all criteria verified), `contract_valid`,
`error_kind`, and `judge_exit`. Default judge consumers recheck the result and actual AC
count rather than trusting an exit code or a RESOLVED claim alone.

## Original inputs and custom tasks

`prepare_inputs.py` validates profiles and `inputs.json`, stages canonical inputs, and
creates read-only hashed snapshots outside the produced workspace. Scorers receive the
trusted snapshot path and validate `.github/eval-inputs.json` against that snapshot's
manifest. No arbitrary metadata pointer, traversal, or symlink is accepted. Only declared
originals may be used as READ-ONLY comparison evidence; context and answers are not dumped.
Unchanged seeded inputs earn no creation credit.

Originals permit checking unchanged production in test-only tasks and comparing original
Helm renders after the produced chart is removed. Render/build verification must use native
tools, not source plausibility. The capped shell artifact dump includes `.github` workflow
deliverables while excluding profiles, internal input metadata, secret/config paths and
build output. Neither truncation nor absence from the dump proves a deliverable is missing.

**Task-10's literal ingress-host equivalence is unresolved**: the six-resource baseline
has no Ingress (its `ingress.host` configures `PUBLIC_BASE_URL`). Do not weaken the AC,
invent an Ingress or assert a pass. If the literal comparison cannot be established,
mark UNVERIFIED with this reason. Other native tool gaps are equally explicit.

Live custom-eval remains **blocked_approval before any model call**; neither scorer nor
this rubric changes mandatory human gates. SWE-bench preparation is not wired and is
reported as setup_error, not failed agent work. Upstream SWE-bench outcomes, once wired,
remain resolved only when FAIL_TO_PASS and PASS_TO_PASS all pass; partial means some
FAIL_TO_PASS pass without regression, failed means verified patch/build/test breakage.

## Aggregates and comparability

`summary.json` retains **every selected task**. Never remove unverified, setup-error,
blocked, or skipped tasks from the denominator. Counts of resolved + partial + failed +
unverified + setup_error_count + blocked_approval_count + skipped equal total. Preflight
failure stops the batch: every selected task is setup_error, with its original preparation
status (`not_prepared` or `setup_error`) retained as context.

Resolved percentage is resolved / total, not resolved / verified. A dry-run total of ten
skipped tasks and a live blocked total of ten tasks are wiring/gate reports, not score 0.

`scorer=both` retains shell-authoritative **normalized** outcomes for comparability.
Both judges return structured completeness and are independently validated; disagreement
is reported with both result records in each task's `grading` object and sidecar JSON.
A verified shell result can remain authoritative when DeepEval is uncertain, but that
uncertainty and disagreement stay visible. No judge's own uncertainty can be bypassed.
Historical results in `eval/baselines.md` are not retroactively recomputed; record new
measurements manually with the contract version and environment limitations.

# Outcome evidence rubric

This is a conceptual reference for retained benchmark tasks and historical
results, **not an active workspace scorer or CLI exit contract**. Active pipeline
scoring measures recorded skill invocation; see
[`../deepeval/README.md`](../deepeval/README.md).
Grading doctrine remains in
[`acceptance-grading`](../../plugins/agile-agents-core/skills/acceptance-grading/SKILL.md).

## Custom tasks

Read each task's actual `acceptance.md`. A resolved outcome requires every
criterion to be verified, not a plausible answer or an unchanged seeded input.

| Outcome | Meaning |
|---|---|
| `resolved` | Every acceptance criterion verified PASS |
| `partial` | Fully verified, with some PASS and non-catastrophic FAIL |
| `failed` | Verified failure, such as a broken build or test regression |
| `unverified` | Missing evidence prevents a verified outcome; no resolved credit |
| `setup_error` | Fixture/environment error, not demonstrated agent failure |

Blocked approvals and skipped tasks are not measured outcomes. Missing tools
are not failures of produced work. Preserve uncertainty and verified failures
explicitly rather than allowing a claimed verdict or permissive threshold to
grant credit.

Original inputs under each task's `baseline/` are comparison evidence, not
answers. `inputs.json` describes their intended workspace destinations. No
staging or verification runtime is supplied. Native build/render/test claims
require native-tool evidence; source plausibility is not a substitute.

**Task-10's literal ingress-host equivalence is unresolved**: the six-resource
baseline has no Ingress (its `ingress.host` configures `PUBLIC_BASE_URL`).
Do not weaken the acceptance criterion, invent an Ingress or assert a pass.
If the literal comparison cannot be established, mark UNVERIFIED with this reason.

## SWE-bench

The retained manifest identifies future benchmark inputs. It does not fetch
datasets, check out repositories or execute tests.
Under the upstream outcome definition, resolved requires all `FAIL_TO_PASS`
and `PASS_TO_PASS` tests to pass. Partial means some `FAIL_TO_PASS` pass without
regression; failed means verified patch/build/test breakage.

## Aggregates and comparability

Keep every selected task in the denominator, including unverified, setup-error,
blocked and skipped tasks. Resolved percentage is resolved / total, not
resolved / verified. A staging report is not an outcome score.

Historical results in [`../baselines.md`](../baselines.md) keep their original
contracts and limitations; they are not retroactively recomputed. The offline
DeepEval skill score is a different measurement and cannot replace those results
in a trend line. Live outcome execution remains deferred to
[#22](https://github.com/hoffe86/agile-agents/issues/22).

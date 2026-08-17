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
| 2026-08-17 | `c6143d8` | Skills with an eval suite             | 14 / 61    | Wave 2 — the collision pairs that genuinely co-install |
| 2026-08-17 | `c6143d8` | Routing accuracy (trigger heuristic)  | 30 / 35    | 2 missed triggers, **3 false triggers** |

**Wave 2 confirmed the collisions are real, not theoretical.** Each negative case is the
*partner skill's* task, so a failure means one skill would answer for another:

| False trigger | Score | Should have been |
|---|---|---|
| `bicep-implementation` on *"bump every AVM module to the latest version"* | 0.80 | `update-avm-modules-in-bicep` |
| `python-testing` on *"run with coverage and drive the missing lines to 100%"* | 0.71 | `pytest-coverage` |
| `conventional-commit` on *"stage the related files and make the commit"* | 0.60 | `git-commit` |

`bicep-implementation` is the sharpest case and its numbers are **inverted**: it scores
**0.80 on its partner's job** and only **0.38 on its own** (*"write the Bicep for a storage
account with private networking"*). Its description over-indexes on module/version
vocabulary and barely describes authoring — which is the failure the collision analysis
predicted from a 0.46 similarity with `update-avm-modules-in-bicep`.

**The one miss carried over from wave 1:** `engineering-judgement` scores **0.46**
(threshold 0.6) on its own core case — *"the ticket doesn't say what should happen when the
upload fails; should I stop and ask, or make the sensible call?"*. Its description is
written in abstract vocabulary that shares few tokens with how the situation is phrased.

Two things not to do with any of these numbers. Do not raise a threshold to clear them,
and do not stuff keywords into a description — the threshold is Waza's uncalibrated
default, and editing prose to move a metric is exactly what `engineering-judgement` §7
forbids. This is why the routing suite **reports** while the frontmatter, drift and token
checks **gate**. Confirm against S1 (observed invocation) before editing any description.

## S1 — observed invocation (first results)

Ground truth for two of the three S0 false triggers. Run via Waza's `copilot-sdk`
executor, 3 trials each; see [`eval/skills/s1-invocation/README.md`](skills/s1-invocation/README.md).

| Date | Collision S0 predicted | S0 heuristic | Observed (3 trials) | Verdict |
|---|---|---|---|---|
| 2026-08-17 | `bicep-implementation` answers for `update-avm-modules-in-bicep` | 0.80 false trigger | **3/3 invoked the correct skill**; the wrong one never fired | **S0 was wrong** |
| 2026-08-17 | `python-testing` answers for `pytest-coverage` | 0.71 false trigger | **0/3 invoked any skill** | **S0 asked the wrong question** |

**The heuristic over-reports collisions.** It compares description vocabulary; the model
has the file and the task shape and disambiguates easily. Rewriting
`bicep-implementation`'s description on S0 evidence would have "fixed" a skill that was
never broken — which is exactly why the routing suite reports rather than gates.

**The bigger finding is the second row.** Asked to close coverage gaps, the agent explored
the fixture, ran coverage, found 13%, wrote 25 tests and reached 100% — invoking
**no skill at all**, not `pytest-coverage`, `python-testing` or `testing-practices`. The
job was done correctly and the library was bypassed.

Contrast the two: the bicep task needed knowledge the model lacks (current AVM versions —
it reached for `web_fetch`) and the skill fired; the pytest task needed nothing the model
cannot already do, and nothing fired. **Hypothesis: skills are invoked when they carry
knowledge the model lacks, and skipped when the model can already do the task.** Two
datapoints, not a conclusion — but it is the question S2 (`--baseline`) exists to settle,
and it matters for all 61.

## S2 — attempted, and it cannot be measured here

`waza run --baseline` reported *"skills have negative/neutral impact (100.0% vs 100.0%)"*.
**That number is an artifact — do not cite it.** The skills-stripped pass invoked
`update-avm-modules-in-bicep` as well, so the A/B compared skills-on against skills-on.
The explicit `--no-skills` flag did not help either.

The cause: the skill is in the developer's **globally installed** plugins, and the
embedded Copilot CLI loads those regardless of Waza's `skill_directories` or flags. Waza
can add skills to a run; it cannot subtract the ones the CLI already has.

S2 therefore needs an **isolated environment** (a container, CI runner, or profile that
never ran `copilot plugin install`), plus a pre-flight check that a `--no-skills` run
invokes nothing at all. Blocked on isolation, not on credits. See
[`eval/skills/s2-efficacy/README.md`](skills/s2-efficacy/README.md).

**The transferable lesson:** a contaminated baseline does not error — it returns a
plausible number that reads like a result. Verify the control pass invoked nothing before
believing any delta.





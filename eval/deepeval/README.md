# DeepEval — offline scoring reference

The operational command scores **existing Copilot JSONL traces** with pinned
DeepEval **4.1.8**. It measures recorded skill invocation, not workspace
acceptance or current-harness benchmark quality. For responsibilities, retained
benchmark data and the Waza/L0 boundaries, see the [evaluation overview](../README.md).
The adoption decision is [ADR 0015](../../docs/adr/0015-deepeval-for-pipeline-evaluation.md).
Live dev-lead runs, scored with this same lock, live in
[`custom-eval`](../pipeline/custom-eval/README.md); they are not OS-sandboxed (#22).

## Install and verify

The reproducibility target is **CPython 3.12 x64**, native Windows and Ubuntu.
The same lock supports **CPython 3.11 x64** developer checks. ARM, PyPy,
Alpine/musl and other Python versions are not locked targets.
Create a fresh environment rather than modifying an existing workspace environment.

```bash
# Windows: py -3.12 -m venv <new-venv>, then <new-venv>/Scripts/Activate.ps1
# Ubuntu: python3.12 -m venv <new-venv>, then source <new-venv>/bin/activate
# An installed CPython 3.11 can be used for developer checks.

# Trusted provisioning: only this download step needs PyPI.
python -m pip --isolated download --index-url https://pypi.org/simple \
    --require-hashes --only-binary=:all: \
    --dest <wheelhouse> -r eval/deepeval/requirements.lock.txt
# Offline install: exact wheels, no source builds or index fallback.
python -m pip --isolated install --no-index --find-links <wheelhouse> \
    --require-hashes --only-binary=:all: -r eval/deepeval/requirements.lock.txt
python -m pip check
python eval/deepeval/check_environment.py
```

The environment check requires the real third-party import, exact version and
deterministic `ToolCorrectnessMetric` score using a fail-on-call model stub.
First-party libraries import as `agile_eval.*` from `eval/python`; that source
root does not shadow third-party `deepeval`.

## Commands

Run from the repository root with the locked environment active:

```bash
# Synthetic fixture demonstration — NOT a current-harness benchmark.
python eval/deepeval/report_skill_usage.py eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl --score --expect-skill fixture-skill-a --output eval/pipeline/runs/skill-fixture-summary.json

# Existing logs — no credentials or new agent runs.
python eval/deepeval/report_skill_usage.py path/to/existing/logs --score --expect-skill architecture-decision-records --output eval/pipeline/runs/skill-usage-summary.json

# Human-readable, stdlib-only parsing report; no DeepEval import.
python eval/deepeval/report_skill_usage.py path/to/existing/logs --expect-skill architecture-decision-records
```

| Argument | Contract |
|---|---|
| `path` | Single UTF-8 JSONL log or a directory; defaults to `eval/pipeline/runs` |
| `--score` | Opt into real pinned DeepEval measurement |
| `--expect-skill NAME` | Repeatable expected identity; scoring requires at least one nonempty value |
| `--output FILE.json` | Required with `--score`, forbidden without it; local JSON summary |

Directories are searched recursively for `.log` and `.jsonl` files in sorted
order, excluding `.copilot-home` and `.copilot` process-log trees.
All selected logs receive the same expectations; narrow the selection or score
files separately for tasks with different requirements.
Legacy runner and live-execution options are unsupported, not offline aliases.

The output parent directory is created if needed. A destination that aliases
an input, including a hard link, is rejected before scoring/writing. Errors
checking file identity fail closed. An existing distinct output may be replaced.

### Measurement

`--score` calls real `ToolCorrectnessMetric.measure()` synchronously with
`evaluation_params=[ToolCallParams.INPUT_PARAMETERS]`. Calls are projected to
`ToolCall(name="skill", input_parameters={"skill": identity})`; prompts, tool
outputs and non-identity arguments never reach the metric.

- Expected identities and recorded calls are deduplicated.
- Score is matched unique expected identities / unique expected identities.
- Expected A with called B scores **0**, even though both use the skill tool.
- One of two expected identities scores **0.5**.
- Extra calls, ordering and repeat invocations do not affect coverage.
- The fixed pass threshold is **1.0**, without rounding away partial evidence.

Negative demonstrations (each deliberately exits 1):

```bash
python eval/deepeval/report_skill_usage.py eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl --score --expect-skill fixture-skill-b --output eval/pipeline/runs/skill-fixture-negative.json
python eval/deepeval/report_skill_usage.py eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl --score --expect-skill fixture-skill-a --expect-skill fixture-skill-b --output eval/pipeline/runs/skill-fixture-partial.json
```

### Input errors and results

The adapter tolerates ordinary non-JSON banners but rejects malformed JSON event
lines (including duplicate fields and nonfinite numbers), non-object events/data,
malformed tool arguments or skill identities, unknown tool events, invalid UTF-8,
and dry-run/setup placeholders. Required signals include tool starts, assistant
turn starts and a nonempty registered-skills list. Missing signals are schema
errors, not proof of skill bypass.

| Scoring exit | JSON status | Meaning |
|---|---|---|
| 0 | `passed`, `passed: true` | Every selected input measured 1.0 |
| 1 | `failed`, `passed: false` | At least one measured score below 1.0 |
| 2 | `schema_error` or `setup_error`, `passed: null` | Invalid trace/input, no inputs, dependency or measurement failure |

Argument errors and unusable output also exit 2; no JSON is promised when the
destination cannot be used. Errors take precedence over measured failures in a
mixed directory. Without `--score`, the text report exits 0 for valid expected
invocations, 1 for bypass/no logs, and 2 for schema/input errors.

JSON schema 1 records `metric`, `deepeval_version`, `scope`, `expected_skills`,
`threshold`, `status`, `passed`, `total`, `measured`, `results` and `errors`.
Each result contains a one-based `input_index` in sorted input order, `status`,
nullable `score`/`passed`, and sanitized structural errors. It omits filenames,
paths, prompts, tool outputs, raw arguments, metric reasons and exception text.
Do not put secrets in operator-supplied expectation labels.

## Offline boundary

The synchronous measure call uses a **fail-on-call model stub**, no
`available_tools` (which activates an LLM path), no `evaluate()` runner and hence
no runner cache or hosted report/upload. Code forces telemetry/update checks off
and disables dotenv/legacy-keyfile loading **before importing DeepEval**.
Set `DEEPEVAL_TELEMETRY_OPT_OUT=1` in the environment too.

The cold-start regression audits network/process attempts from import through
measurement, even with synthetic ambient keys and telemetry/update opt-ins, and
asserts only the requested local summary is created. It does not prewarm platform
metadata or override socket capabilities. It permits only two narrow trusted
initialization operations: CPython's Windows metadata `cmd.exe /c "ver"` from
`platform._syscmd_ver`, and urllib3's IPv6 capability bind to `::1` on port 0.
Neither is an external connection, model/agent run, or recorded command/artifact
execution. Connection/DNS attempts and other process/bind attempts are rejected
and recorded even if a dependency catches the exception.

This is evidence for the exercised offline scoring path, **not** a claim of zero
subprocesses or zero socket operations, and not an OS sandbox.
A supplied log is not authenticated model/runtime evidence. Recorded invocation
does not prove successful completion, correct skill use, task quality or L2
resolved credit. `skill-scoring-demo.jsonl` is synthetic;
`copilot-session.jsonl` is the sanitized real-log adapter regression.

## Tests and local gates

```bash
# PowerShell: $env:EVAL_REQUIRE_DEEPEVAL = '1'
export EVAL_REQUIRE_DEEPEVAL=1
export DEEPEVAL_TELEMETRY_OPT_OUT=1
python -m pytest eval/deepeval/tests eval/pipeline/custom-eval/tests -q
python -m unittest discover -s eval/pipeline/tests -p test_dependency_environment.py -v
python scripts/run-repo-checks.py lint
python scripts/run-repo-checks.py unit
```

`EVAL_REQUIRE_DEEPEVAL=1` makes dependency-dependent pytest tests fail on a
missing/broken import instead of skipping. Tests exercise real identity scores,
malformed inputs, dependency failures, output alias protection, cold startup,
canonical imports and rejection of retired entrypoints/options.
Benchmark consistency tests inspect source data without running its commands.
The local selectors preserve the unittest/pytest split and deterministic
trajectory checks.

## Dependency maintenance

`requirements.txt` is maintainer input, not an installation command.
`requirements.lock.txt` pins the complete transitive pip closure rooted at
DeepEval **4.1.8**, pytest **9.1.1** and PyYAML **6.0.3**.
`requirements-yaml.lock.txt` owns shared PyYAML hashes for lightweight skill checks.
The interpreter's bundled pip bootstraps installation; no extra manager is needed.

Hashes cover downloaded wheel bytes. Pure-Python wheels share hashes; native
wheels cover CPython 3.11/3.12 Windows `win_amd64` and Ubuntu `manylinux` x86_64.
`colorama` is Windows-only. Pip selects compatible wheels and fails closed otherwise.

For an explicitly approved dependency change:

1. Retain unaffected versions and review resolution with pip's dry-run report;
   do not blanket-upgrade the closure. ADR 0015's DeepEval pin is binding.
2. Download exact wheels on supported Python/platform targets with
   `--only-binary=:all:` and hash each approved artifact with `python -m pip hash`.
3. Check installed metadata, including extras and environment markers.
   Cross-target downloads do not prove native execution.
4. Repeat hash-verified installation, `pip check`, the required-import gate and
   offline tests in clean native environments.

Dependency tests verify the installed closure and use a local metadata-only wheel
to prove tampered/missing hashes and missing artifacts fail without index fallback
or generated package-code execution.

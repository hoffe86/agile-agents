# DeepEval spike — pipeline (agent / E2E) evaluation

Status: **spike**. Decision and risks in [ADR 0015](../../docs/adr/0015-deepeval-for-pipeline-evaluation.md).
The native harness in [`../pipeline/`](../pipeline/) remains available. Both outcome
judges now share the strict structured contract in
[`agile_eval.grading_contract`](../python/agile_eval/grading_contract.py).

First-party implementation is under [`../python/agile_eval/`](../python/agile_eval/),
including `metrics` and `adapters`. This directory retains dependency locks, tests,
and the existing executable script paths. Import libraries through `agile_eval.*`;
adding only `eval/python` to the source path does not shadow third-party `deepeval`.

**Live scoring is currently disabled.** DeepEval is still available for offline parser,
metric-contract, and fixture tests, but `run_judge` returns `UNVERIFIED` without sending
workspace content to a model or invoking host tools. Live agent runs are blocked by the
pipeline runner. The future credential-free worker boundary denies external/host/control-plane
networking for untrusted artifact execution; it does not describe the model API caller,
which needs network and authentication. HOME/tempdir/PATH hygiene is not OS isolation,
and dry staging is not execution-readiness certification. Task-local loopback/database
policy is still unapproved. See the [safety hold](../README.md#live-evaluation-safety-hold).

## What this proves

ADR 0015 adopts DeepEval for the pipeline layer, gated on a spike answering two questions.
Both are now answered, on real data:

**1. Can a Copilot CLI run be turned into a DeepEval trace?** Yes. `copilot -p … --output-format json` emits
newline-delimited JSON carrying `id` / `parentId` / `timestamp` — already a span tree.
[`agile_eval.adapters.copilot_trace`](../python/agile_eval/adapters/copilot_trace.py) reconstructs the ordered tool
calls from it. DeepEval ships integrations for LangChain, OpenAI, Anthropic and others but
none for Copilot CLI; this adapter is that missing piece.

**2. Does it run offline, without a subscription?** Yes. Verified on DeepEval 4.1.8 with no
login, no API key, telemetry opted out and `HTTP(S)_PROXY` blackholed — with the proxy
itself falsified first, so the result is not a silent success.

The measurement that matters falls out of it: **invoking a skill is a tool call named
`skill`**, so skill bypass is directly observable.

```json
{"toolName":"skill","arguments":{"skill":"architecture-decision-records"}}
```

## Run it

Use **CPython 3.12 x64** for the reproducibility target (native Windows and Ubuntu
CI lanes). The same lock also includes CPython **3.11 x64** wheels for developer
checks; the profile's `python scripts/run-repo-checks.py lint|unit` does not require
3.12. ARM, PyPy, Alpine/musl and other Python versions are not locked targets.
Create a fresh venv rather than changing an existing workspace environment:

```bash
# Windows: py -3.12 -m venv <new-venv>, then <new-venv>/Scripts/Activate.ps1
# Ubuntu: python3.12 -m venv <new-venv>, then source <new-venv>/bin/activate
# For developer compatibility checks, use an installed CPython 3.11 instead.

# Trusted provisioning: only this download step needs PyPI.
python -m pip --isolated download --index-url https://pypi.org/simple \
    --require-hashes --only-binary=:all: \
    --dest <wheelhouse> -r eval/deepeval/requirements.lock.txt
# Offline install from those exact wheels; no source builds or index fallback.
python -m pip --isolated install --no-index --find-links <wheelhouse> \
    --require-hashes --only-binary=:all: -r eval/deepeval/requirements.lock.txt
python -m pip check
python eval/deepeval/check_environment.py

# Offline tests (PowerShell: $env:EVAL_REQUIRE_DEEPEVAL = '1').
export EVAL_REQUIRE_DEEPEVAL=1
export DEEPEVAL_TELEMETRY_OPT_OUT=1
python -m unittest discover -s eval/pipeline/tests -p test_dependency_environment.py -v
python -m unittest discover -s eval/pipeline/tests -p test_native_controller.py -v
python -m pytest eval/deepeval/tests -q

# measure skill usage across existing run logs — no credentials, no new runs
python eval/deepeval/report_skill_usage.py eval/pipeline/runs \
    --expect-skill architecture-decision-records
```

Importing `agile_eval.report_skill_usage` leaves streams unchanged; its CLI `main()`
configures UTF-8 before producing the normal report.

`DEEPEVAL_TELEMETRY_OPT_OUT=1` is set in code before DeepEval is imported
([`agile_eval.metrics.local_model`](../python/agile_eval/metrics/local_model.py)), because opting out after import is
too late. Set it in CI as well — belt and braces.

### Dependency lock and maintenance

`requirements.txt` is the **maintainer input**, not an installation command.
`requirements.lock.txt` is the complete transitive pip requirements closure:
DeepEval **4.1.8**, github-copilot-sdk **1.0.22**, pytest **9.1.1**, PyYAML **6.0.3**,
and exact dependency versions.
Versions were retained from the working evaluation venv, not broadly upgraded.
The exception is setuptools **84.0.0**, already present in the developer environment;
the old venv's **65.5.0** predates Python 3.12 and references removed
`pkgutil.ImpImporter`. No new manager, resolver, runtime dependency or pip upgrade
is introduced. The interpreter's bundled pip bootstraps installation.

The lock uses ordinary pip SHA-256 hashes of **downloaded wheel bytes**, not hashes
of source text or invented integrity values. Pure-Python wheels share one hash;
native wheels have hashes for CPython 3.11/3.12 Windows `win_amd64` and Ubuntu
`manylinux` x86_64. `colorama` has the Windows-only marker required by pytest,
Click, Typer and tqdm. Pip selects compatible wheels and fails closed otherwise.
`requirements-yaml.lock.txt` owns the PyYAML hashes and is included by the full lock;
the skill-quality lane uses only that lightweight file.

The already-adopted SDK uses this same closure for ordinary callback unit tests,
not a separate environment. Its added transitive pins are httpx **0.28.1**,
httpcore **1.0.9**, python-dateutil **2.9.0.post0**, and six **1.17.0**; existing
shared versions and platform hashes are unchanged. The tests assert the actual
`PlanReadResult` and `PermissionDecisionReject` contracts and the SDK's declared
CLI version **1.0.98**, without installing or launching that CLI. SDK imports
are local to those tests; missing or incompatible dependencies fail with the
shared-lock install command. Client construction, sockets and subprocesses are
forbidden, and the production readiness path remains SDK-free and held.

CI creates a fresh venv, downloads with `--require-hashes --only-binary=:all:`,
installs with `--no-index`, runs `pip check`, then requires the real DeepEval import,
real `BaseMetric` inheritance, and deterministic `ToolCorrectnessMetric` score with
the fail-on-call stub. `EVAL_REQUIRE_DEEPEVAL=1` makes both dependency-dependent
pytest tests fail on a missing/broken import instead of skipping. The isolated
dependency-free parser regression remains valid. Telemetry opt-out and offline test
design **are not OS network isolation** and do not release the live-evaluation hold.

To update deliberately:

1. Review the requested version changes in `requirements.txt` and the existing
   pinned closure; retain unchanged versions. ADR 0015's DeepEval pin is binding.
2. Use pip's `install --dry-run --ignore-installed --report <report.json>` with
   reviewed constraints to inspect any necessary resolution changes. Do not
   replace the closure with a blanket latest-version resolution.
3. Download the candidate exact closure on each native supported Python/platform
   with `pip download --only-binary=:all:`; use `python -m pip hash <wheel>` for
   each approved artifact and review the lock diff. No source distributions.
   For preliminary cross-target checks, use `--python-version 311` / `312`,
   `--implementation cp`, `--abi cp311` / `cp312`, and `--platform win_amd64`, or
   `--platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64
   --platform manylinux2014_x86_64`. Cross-target pip options choose wheel tags;
   **they do not prove native execution or target environment-marker evaluation**.
   Inspect wheel `METADATA` for both target marker environments as well.
4. In clean native environments, repeat the hash-verified install, `pip check`,
   required-import gate and offline tests above. The dependency tests verify
   the complete installed metadata closure and mutate a local metadata-only fake
   wheel to prove tampered hashes, missing hashes and missing artifacts fail.
   No package code is executed by that fake-wheel test.

Initial validation: all four target wheel sets downloaded and were hash-checked;
native clean-environment execution was performed on Windows Python 3.11.9.
Python 3.12 was not installed locally. **Native Windows/Ubuntu Python 3.12 CI is
still required**; cross-target downloads are not a substitute.

## Outcome grading

Fresh retained results keep schema 2 and sanitized criteria, with a separate
version-1 provenance sidecar. Native runner consumers require the runner-held
expected context digest; parsing a plausible verdict alone cannot award credit.
See [retained run provenance](../README.md#retained-run-provenance) for hash scope,
legacy handling, unavailable tool/model identities and the unsigned integrity boundary.
This does not lift the live-verification hold.

`agile_eval.grading` coordinates held preflight and prompt composition.
`grading_contract` owns pure verdict normalization, `workspace_inputs` verifies fixture
origins, and `provenance` owns retained results and their bindings, using bounded
`file_io` primitives. These dependencies are one-way, with no provenance-to-grading import.
`score_workspace.py` delegates without importing DeepEval; `agile_eval.metrics.acceptance`
adapts it to the native framework. `score-judge.{sh,ps1}` and `shell_judge.py` are
compatibility forwarders only:

```bash
# scorer — 0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup or judge error
python eval/deepeval/score_workspace.py <workspace> <acceptance.md> \
    --isolated-home <dir> --baseline-dir <immutable-dir> --result-json <result.json>

# contract check, no CLI call and no network
python eval/deepeval/score_workspace.py --self-test
```

`AcceptanceMetric` is a real DeepEval `BaseMetric`, exercised through actual
DeepEval **4.1.8** `evaluate()` in the offline integration test. Missing/broken
dependencies fail clearly; there is no fallback `object` metric. Pure parsing in
`agile_eval.grading_contract` and held CLI preflight remain usable without DeepEval. No positive
workspace measurements are fabricated to demonstrate framework adoption.

Native evaluation must use `CacheConfig(write_cache=False, use_cache=False)`:
4.1.8 defaults to writing cache, and native cache keys do not bind workspace bytes.
The integration test uses `DisplayConfig(results_folder=<owned-temp-dir>,
inspect_after_run=False)` and an empty, credential-free HOME/config/current
directory, with network/process denial installed **before imports**. Telemetry
opt-out and `official=False` alone do **not** guarantee no Confident upload.
No Confident result uploads, model calls or custom cache are used.
API/defaults were checked against installed 4.1.8 and the official
[`v4.1.8` configs](https://github.com/confident-ai/deepeval/blob/v4.1.8/deepeval/evaluate/configs.py).

**Parity is tested, not asserted.** The verdict parser is exercised against the exact cases
`score-judge.sh --self-test` uses. Exactly one anchored final verdict and one numbered
PASS/FAIL/UNVERIFIED line per actual acceptance criterion are required. Missing, duplicate,
or malformed lines produce `setup_error` (`judge_contract`), not an agent failure.
Real Python/PowerShell/Bash entrypoints are tested for inventory, path/regex/argument
parity, startup injection resistance, baseline/provenance integrity, dependency errors
and held status. Old source-sliced shell execution and fake comparison tests were retired
with the deleted runtime. No tests authorize executing generated artifacts.

Historical orientation lessons still apply:

- **Its orientation is a file index rather than a dump.** The old prompt inlined file contents and told
  the grader to decide "strictly from those artifacts", so a truncated listing became
  evidence of absence — a task was once failed for missing tests that existed and passed.
  The intended live judge uses a file index for orientation, but current scorer entry points
  return `UNVERIFIED` without passing workspace content to a model or invoking tools.
- **Doctrine lives in the `acceptance-grading` skill**, not in the prompt. The prompt is a
  shim that loads it. Restating grading rules in an eval-private template is the same
  fork-then-drift that caused the MADR mismatch.

`UNVERIFIED` denies resolved credit: score 0, exit 3, and `metric.success=False` even
with threshold 0. Verified failures remain in the per-criterion record; FAIL+UNVERIFIED
with no verified pass normalizes to FAILED, while all-unverified is UNVERIFIED. JSON
reports `claimed_verdict`, normalized status, criterion ids/statuses, `complete`
(verification), `contract_valid`, and `error_kind`. CLI nonzero exit, timeout, and missing
CLI are setup/judge errors (exit 4), not fabricated agent failures.

Regression expectation corrected explicitly: `test_metric_surfaces_unverified_in_the_reason`
formerly asserted `metric.measure(Case()) == 1.0` for a claimed RESOLVED response with an
UNVERIFIED criterion. That assertion rewarded unknown evidence as full success. It now
asserts score `0.0` and `is_successful() is False`; this is a corrected invalid expectation,
not a weakened test. Bare/duplicate verdict and timeout/missing-CLI tests now assert
structured judge/setup errors instead of invented agent failures.

Immutable originals are validated against the staged manifest and hashes before and after
scoring preflight. Pass `--baseline-dir` from the harness; without it, only the canonical sibling
`<run>/ws/<task>` / `<run>/baseline/<task>` layout is accepted. Agent-editable metadata
cannot redirect the scorer to arbitrary paths. Originals are integrity-checked comparison
inputs, not produced answers or baseline credit; mode bits do not provide an OS access
boundary. Task-10's literal ingress-host equivalence versus
the six-resource no-Ingress baseline remains unresolved: inability to verify it must be
UNVERIFIED, as must other native-tool gaps.

Run the complete offline suite from the active locked environment (unittest for
script/workflow/trajectory checks, pytest for custom-eval and DeepEval):

```bash
python scripts/run-repo-checks.py unit
```

On Windows the native tests use PowerShell 7 and Git Bash; on Unix they use `pwsh` and
`bash`. Shells run by absolute executable path (the native `Git/usr/bin/bash.exe`, not
the PATH-extending wrapper). Utilities are individually exposed in a temporary command
directory, never by adding a shell's host directory such as `/usr/bin` to PATH.
The fixture preserves the active Python executable's original parent on PATH:
resolving a POSIX venv symlink first would lose the locked dependencies.
Thin launchers start `run_eval.py` with `-I -S -B`; Python exposes only its selected
interpreter's package directories, without executing `.pth` or site startup hooks.
**Python is prerequisite to an attempt.** Without it, launchers exit 2 with a clear
diagnostic and no artifacts. Once Python starts and selects tasks, setup failures
retain the full selected inventory, including all ten tasks for a full suite.
Prompt readability is checked during preflight and rechecked after staging.

`deepeval` remains the only/default runner scorer. `--scorer shell|both` is retired
with an argument error, not mapped to another backend. Current unscored percentages
are null; no fake agreement is reported. Historical source is available at git ref
`ccafa13e1c782220db001ac081433dca2ae1df54`, which also retains the live hold.
ADR 0015's historical shell-retention note does not describe the current runtime.
Waza's skills-layer responsibility is unchanged. Live evaluation stays held before
staging, SDK imports or token reads; mandatory human plan approval remains separate.

## Findings so far

**Task-04 did *not* bypass its skill — until isolation was switched on.** The two
contaminated runs invoked `architecture-decision-records`; the two isolated runs did not.
The likely mechanism is that contaminated runs loaded the *installed* `agile-agents-core
v0.14.0` agent while isolated runs load the working tree at `v0.16.0` — which is exactly
what isolation exists to reveal. Two runs either side is a signal to investigate, not a
conclusion.

**The eval has been rewarding skill bypass.** Correlating skill invocation with output
shape shows it cleanly:

| Run | Skill invoked | ADR shape produced | Judge |
|---|---|---|---|
| contaminated ×2 | yes (v0.14.0 skill → MADR) | `Context and Problem Statement / Decision Drivers / …` | partial |
| isolated ×2 | no | `Status / Context / Decision / Consequences / Alternatives / Related decisions` | resolved |

Historically, task-04's criterion 2 demanded "all six MADR sections in order: Status, Context, Decision,
Consequences, Alternatives, Related decisions" — a list that is neither upstream MADR nor
this repo's Nygard house style. The runs that consulted a skill produced something the
criterion rejected; the runs that consulted nothing produced what the criterion happened to
describe. **A criterion that restates a convention it does not own can invert the incentive
it was meant to create.** This is the concrete case behind the `acceptance-grading` rule
that the skill wins and the judge reports the drift as an eval defect.

The current fixture repairs that contract: it selects the core skill's MADR template,
allows exactly the new ADR and working-copy predecessor, and requires bidirectional
supersession links without changing the canonical sibling original. No answer ADR is
seeded. Both shell and DeepEval offline prompt builders now include the authoritative
`acceptance-grading` content through the shared renderer, including the no-host-execution
hold. This repair is deterministic contract work, not a new live outcome measurement;
the historical scores above are not regraded.

**Task-04 did *not* bypass its skill.** Both real runs invoked
`architecture-decision-records`. The earlier skill-bypass hypothesis rested on three
anecdotes; the first actual measurement contradicts it for this task. Whether that is
because the prompt now names the skill is a separate question, and one this tooling can
answer by comparing runs.

**The eval session was contaminated by the developer's environment — and isolation fixes
it.** `--plugin-dir` does not override an already-installed plugin of the same name, so runs
were measuring the installed `agile-agents-core v0.14.0` rather than the working tree at
`v0.16.0`. Plugins install at **User** scope under the home directory, so pointing
`USERPROFILE` / `HOME` at a throwaway directory removes them and leaves `--plugin-dir` as the
only source. Proven by probe: the question that returned stale installed text now returns the
working-tree text. Auth does not survive isolation, so the run needs `GH_TOKEN` supplied —
which is how CI would do it anyway. This is a **precondition** for trusting any number here.

**`skills_offered` is not a denominator.** `session.skills_loaded` lists *registered* skills
(User-scope plugins and builtins), not those supplied via `--plugin-dir`, which resolve on
demand. An isolated session reports 2 loaded skills while happily invoking a `--plugin-dir`
one. Use `skills_invoked` to measure bypass; do not compute a rate against `skills_offered`.
See ADR 0015.

## Why the schema guard exists

The CLI log format is undocumented. An adapter bound to it fails **silently**: rename
`tool.execution_start` and the trace comes back empty — which is indistinguishable from an
agent that invoked nothing. That is the same shape as the three defects found on
2026-08-19, all of which produced plausible numbers while measuring nothing.

`verify_schema()` turns that into a visible complaint, and the tests mutate the fixture to
prove the guard actually fires rather than assuming it would. `report_skill_usage.py`
exits `2` on schema drift specifically so it cannot be mistaken for an agent result.

The test fixture is distilled from a real run log, sanitised of absolute paths — not
hand-written, so it cannot drift into agreeing with the parser.

## Models

Two categories, per ADR 0015:

| Metric | Needs a model? |
|---|---|
| `ToolCorrectness` (skill bypass) | Constructor requires one; **never invokes it** (`llm_calls=0`). `stub_model()` satisfies it with no credentials. |
| Custom `BaseMetric` (build/test outcome) | No — it runs commands. |
| Task Completion, Plan Adherence, Plan Quality, Step Efficiency | Yes, genuinely. |

For the last row, `azure_openai_model()` wraps DeepEval's `AzureOpenAIModel`, which accepts
either `AZURE_OPENAI_API_KEY` or `azure_ad_token_provider` — so Azure OpenAI (including a
deployment inside an AI Foundry resource) works, and CI can stay passwordless via Entra ID.
Ollama is supported natively for a fully local judge.

DeepEval is **pinned** — `ToolCorrectness` being deterministic despite demanding a model is
an implementation detail, not a documented contract.

## Not done yet

- Isolated Copilot configuration root, without which the numbers above measure the
  developer's machine rather than the branch.
- Trajectory metrics (Plan Adherence against the Stage 4 plan) — needs the span tree built
  into nested DeepEval spans, not just the flat ordered tool list.
- Outcome grading via custom `BaseMetric`, hosting the `acceptance-grading` skill.
- Deciding the fate of `../pipeline/` — replace, or keep as the fallback ADR 0015 names.

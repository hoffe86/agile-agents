# DeepEval spike — pipeline (agent / E2E) evaluation

Status: **spike**. Decision and risks in [ADR 0015](../../docs/adr/0015-deepeval-for-pipeline-evaluation.md).
The existing harness in [`../pipeline/`](../pipeline/) is untouched and remains the
fallback if this spike fails.

## What this proves

ADR 0015 adopts DeepEval for the pipeline layer, gated on a spike answering two questions.
Both are now answered, on real data:

**1. Can a Copilot CLI run be turned into a DeepEval trace?** Yes. `copilot -p … --output-format json` emits
newline-delimited JSON carrying `id` / `parentId` / `timestamp` — already a span tree.
[`adapters/copilot_trace.py`](adapters/copilot_trace.py) reconstructs the ordered tool
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

```bash
python -m venv eval/deepeval/.venv
eval/deepeval/.venv/Scripts/python -m pip install -r eval/deepeval/requirements.txt

# tests (the parsing half needs no DeepEval and no network)
eval/deepeval/.venv/Scripts/python -m pytest eval/deepeval/tests -q

# measure skill usage across existing run logs — no credentials, no new runs
python eval/deepeval/report_skill_usage.py eval/pipeline/runs \
    --expect-skill architecture-decision-records
```

`DEEPEVAL_TELEMETRY_OPT_OUT=1` is set in code before DeepEval is imported
([`metrics/local_model.py`](metrics/local_model.py)), because opting out after import is
too late. Set it in CI as well — belt and braces.

## Outcome grading

`metrics/acceptance.py` replaces the `score-judge.{sh,ps1}` twin pair with one Python
implementation, exposed two ways:

```bash
# drop-in scorer — same exit contract as score-judge: 0 resolved, 2 partial, 1 failed
python eval/deepeval/score_workspace.py <workspace> <acceptance.md> --isolated-home <dir>

# contract check, no CLI call and no network
python eval/deepeval/score_workspace.py --self-test
```

`AcceptanceMetric` is a real DeepEval `BaseMetric` (checked with `issubclass`, because
DeepEval type-checks with `isinstance` and duck typing is rejected), so it composes with
`evaluate()` and the rest of the framework.

**Parity is tested, not asserted.** The verdict parser is exercised against the exact cases
`score-judge.sh --self-test` uses — last verdict wins, case-insensitive, unparseable is
FAILED so an unclear judge never inflates a score. Verified end-to-end as well: on the same
task-04 workspace, the shell judge and this metric both return `RESOLVED`.

Two deliberate differences from the shell judge:

- **It verifies instead of reading a dump.** The old prompt inlined file contents and told
  the grader to decide "strictly from those artifacts", so a truncated listing became
  evidence of absence — a task was once failed for missing tests that existed and passed.
  Here the judge runs *in* the workspace with tools; the file listing is an orientation
  index, explicitly labelled as not the workspace, and build output is pruned.
- **Doctrine lives in the `acceptance-grading` skill**, not in the prompt. The prompt is a
  shim that loads it. Restating grading rules in an eval-private template is the same
  fork-then-drift that caused the MADR mismatch.

`UNVERIFIED` is surfaced separately and never folded into the score: it means the harness
failed to show the judge evidence, which understates the agent.

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

Task-04's criterion 2 demands "all six MADR sections in order: Status, Context, Decision,
Consequences, Alternatives, Related decisions" — a list that is neither upstream MADR nor
this repo's Nygard house style. The runs that consulted a skill produced something the
criterion rejected; the runs that consulted nothing produced what the criterion happened to
describe. **A criterion that restates a convention it does not own can invert the incentive
it was meant to create.** This is the concrete case behind the `acceptance-grading` rule
that the skill wins and the judge reports the drift as an eval defect.

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

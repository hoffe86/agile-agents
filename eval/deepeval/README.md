# DeepEval spike — pipeline (agent / E2E) evaluation

Status: **spike**. Decision and risks in [ADR 0015](../../docs/adr/0015-deepeval-for-pipeline-evaluation.md).
The existing harness in [`../pipeline/`](../pipeline/) is untouched and remains the
fallback if this spike fails.

## What this proves

ADR 0015 adopts DeepEval for the pipeline layer, gated on a spike answering two questions.
Both are now answered, on real data:

**1. Can a Copilot CLI run be turned into a DeepEval trace?** Yes. `copilot -p … -s` emits
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

## Findings so far

**Task-04 did *not* bypass its skill.** Both real runs invoked
`architecture-decision-records`. The earlier skill-bypass hypothesis rested on three
anecdotes; the first actual measurement contradicts it for this task. Whether that is
because the prompt now names the skill is a separate question, and one this tooling can
answer by comparing runs.

**The eval session is contaminated by the developer's environment.** Both runs were
offered **88 skills** while the repository defines **62** — 26 arrived from other globally
installed plugins. Combined with the finding that `--plugin-dir` does not override an
already-installed plugin of the same name, this means an eval run does not measure the
working tree. Isolation is a precondition for trusting any number this produces, not a
later refinement. See ADR 0015.

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

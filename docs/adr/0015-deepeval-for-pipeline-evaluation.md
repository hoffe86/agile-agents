# ADR 0015 — Evaluate the pipeline layer with DeepEval, keeping Waza for skills

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (pipeline evaluation tooling)
- **Related:** ADR 0014 (skills-layer evaluation with Waza — this sits beside it, neither supersedes the other), ADR 0008 (layered evaluation strategy — this extends the pipeline layer)

## Context

`eval/` measures two different things. Skills are evaluated in `eval/skills/` on Waza
([ADR 0014](0014-skill-evaluation-with-waza.md)). Whole `dev-lead` runs are evaluated in
`eval/pipeline/` on a hand-written harness — 941 lines split across `run-eval.{sh,ps1}` and
`score-judge.{sh,ps1}`. That harness measures outcomes only: did the produced workspace satisfy
the acceptance criteria. It cannot observe *how* the run reached them.

Two forces make this a decision now.

**The harness is an ongoing defect source.** On 2026-08-19 a single investigation surfaced a
`score-judge.ps1` artifact-collection loop that had never worked since PR #1 (variables never
assigned, 147 empty blocks, invisible because the `.sh` twin worked), `awk` and bash 5.3 both
expanding `&` in a replacement to the matched text and corrupting 2 of 10 task prompts, and a
dry run printing `Failed: 1/1` while exiting `PASS`. Three of roughly seven defects trace
directly to maintaining `.sh` and `.ps1` twins by hand.

**The questions we most want answered are trajectory questions.** Agents appear to bypass
installed skills — but that rests on three anecdotes, because nothing measures skill invocation.
Likewise, nothing checks whether `dev-lead` follows the plan it committed to at Stage 4. Outcome
scoring cannot answer either, no matter how correct it becomes.

## Decision

**Adopt DeepEval for the pipeline layer. Keep Waza for the skills layer.** The two layers stay on
different tools deliberately, each matched to its unit of evaluation.

The enabling fact was established by inspecting a real run log, not assumed: **Copilot CLI's `--output-format json`
output is already a structured span tree.** One task-04 run emitted 1,420 JSONL events, each
carrying `id` / `parentId` / `timestamp`, including `tool.execution_start`,
`tool.execution_complete`, `assistant.turn_start` / `turn_end` and `session.skills_loaded`. Tool
events carry `toolName` and full `arguments` — and **skill invocation is itself a tool call**:

```json
{"toolName":"skill","arguments":{"skill":"architecture-decision-records"}}
```

DeepEval ships no Copilot CLI tracing integration, but everything needed to synthesise one is
already written to disk on every run.

Adoption is **gated on a spike**: build the log→trace adapter plus one `ToolCorrectness` metric,
run it over logs already in `eval/pipeline/runs/`, and confirm both that the trace reconstructs
faithfully and that DeepEval transmits nothing off-machine. If either fails, supersede this ADR
in favour of the Python-port alternative below, which captures the twin-removal benefit alone.

`acceptance-grading` remains the owner of grading doctrine — DeepEval would host that skill, not
replace it. Workspace staging, `fixture/` handling and `copilot` invocation remain ours under any
option; the framework absorbs roughly 40% of the existing harness, not all of it.

## Consequences

**Trajectory questions become measurable rather than anecdotal.** `ToolCorrectness` against
`expected_tools` turns skill bypass into a metric with a threshold. Plan Adherence maps onto the
RPI pipeline's plan-then-implement shape. Neither is answerable today.

**The first measurements need no new runs and no Copilot credits** — existing logs in
`eval/pipeline/runs/` are retroactively analysable.

**The `.sh`/`.ps1` twins disappear**, removing the defect class that concealed a completely broken
`score-judge.ps1` for the life of the repository. Python is already a repository dependency
(`check-skill-frontmatter.py`, `check-instructions-drift.py`), so no new toolchain is introduced.

**Commodity scaffolding is inherited rather than hand-written** — pytest integration, metric
caching, multiprocessing, CI reporting.

Against that:

- **The Copilot CLI log schema is undocumented and may change without notice.** The adapter
  couples us to another product's internals, and a silent schema change would break trajectory
  metrics. Keep the adapter narrow and add a schema-drift check in the shape of
  `check-instructions-drift.py`.
- **Trajectory metrics are LLM-judged**, so non-deterministic — the same class of problem fought
  on the outcome side, now present in the process measurement too.
- **DeepEval nudges toward its hosted Confident AI platform** (`deepeval login`, automatic report
  upload). This must be verified off by default and kept off, or the repository content policy is
  breached. This is a gating check in the spike, not a later cleanup.
- A framework's concepts (goldens, test cases, metrics) get imposed on a harness whose failure
  modes are now well understood after extended debugging.

## Verification (2026-08-19)

The offline and cost preconditions were tested rather than assumed, in a throwaway venv on
DeepEval **4.1.8** with no login, no API key, `DEEPEVAL_TELEMETRY_OPT_OUT=1`, and `HTTP(S)_PROXY`
pointed at a blackhole. The proxy was itself falsified first (a control request failed with
`ProxyError`), so the offline result is meaningful rather than a silent success.

- **No subscription is required.** Confident AI is opt-in behind an explicit `deepeval login`.
- **Both halves of this decision run with zero network.** `ToolCorrectness` scored 1.0 when the
  `skill` tool appeared in `tools_called` and 0.0 when it did not — the skill-bypass measurement
  works offline. A custom `BaseMetric` shelling out to a subprocess scored 1.0/0.0 correctly,
  confirming execution-based outcome grading needs no model.
- **Correction to the Decision section above:** `ToolCorrectness` was characterised as cheap and
  effectively free. In 4.1.8 its constructor calls `initialize_model()` and **raises without an
  `OPENAI_API_KEY`**, even though it never actually invokes the model (`llm_calls=0` while scoring
  correctly). It is deterministic in behaviour with a spurious construction-time dependency,
  satisfiable by a one-line `DeepEvalBaseLLM` stub. Pin the DeepEval version — this is an
  implementation detail, not a documented contract.
- **Telemetry is on by default** and sends event names, metric names, an anonymous UUID and the
  **public IP** to PostHog. `DEEPEVAL_TELEMETRY_OPT_OUT=1` must be set in CI and locally.
- **It fails closed.** With no key and no model it raises rather than emitting a fabricated score
  — the right default given how much of this harness's history is silent degradation producing
  plausible numbers.
- **Azure OpenAI is first-class**, via `AzureOpenAIModel` / `deepeval set-azure-openai`, taking
  either `AZURE_OPENAI_API_KEY` or `azure_ad_token` / `azure_ad_token_provider` — so Entra ID
  passwordless auth works and CI need hold no static key. This covers Azure OpenAI deployments
  including those in an AI Foundry resource; Foundry's wider model catalogue (Azure AI Inference)
  would need the same thin custom-model shim the probe already exercised.

### The plugin-shadowing defect this work uncovered

While verifying an unrelated skill change, `--plugin-dir` was found **not to override an
already-installed plugin of the same name** — it only contributes skills that have no installed
counterpart. A direct probe returned the installed, stale skill text while the edited working-tree
copy was ignored.

`run-eval` and `score-judge` both pass `--plugin-dir` believing they exercise the working tree, so
**any measurement of a modified existing skill has been reading the installed copy instead.** This
is the same family as the S2 contamination in ADR 0014 that produced "skills have neutral impact".

**Resolved (2026-08-19): an isolated configuration root fixes it, and it is now wired into the
harness.** Plugins are installed at **User** scope under the home directory, so redirecting
`USERPROFILE` / `HOME` to a per-run throwaway directory removes them from resolution and leaves
`--plugin-dir` as the only source. Verified by probe: the same question that previously returned
the stale installed text (`PHRASE: no`) returns the working-tree text (`PHRASE: yes`) under an
isolated home. Auth does not survive isolation, so the run must be given a token — which is how
CI would supply it anyway, and the harness now **exits 2** rather than falling back.

The installed copy was `agile-agents-core v0.14.0` while the working tree was at `v0.16.0` — two
minor versions of drift, silently winning.

MCP servers split the right way: the developer's personal servers are dropped, while those the
plugins declare themselves (`plugins/agile-agents-core/.mcp.json` — context7, microsoft-docs,
playwright) still load because they arrive via `--plugin-dir`. Task-04 depends on `microsoft-docs`
for its primary-sources criterion and scores `resolved` under isolation, so the capability the
harness declares survives while the ambient environment does not.

**Correction to an earlier reading of this data.** The observation "88 skills offered where the
repo defines 62" was evidence of contamination, but `session.skills_loaded` turns out to list
**registered** skills (User-scope plugins and builtins) and **not** those supplied via
`--plugin-dir`, which resolve on demand instead. An isolated session reports only 2 loaded skills
(both builtin) while still successfully invoking a `--plugin-dir` skill. So `skills_offered` is not
a measure of what the agent could reach, and must not be used as a denominator for a bypass rate.
`skills_invoked` — the measurement this decision rests on — is unaffected.

## Alternatives considered

**Port the bespoke harness to a single Python implementation.** Delete the `.sh` twins,
reimplement `run-eval` and `score-judge` once, change nothing about what is measured. This removes
the largest observed defect class at the lowest cost, adds no dependency, and carries no
data-egress risk. Rejected as insufficient rather than wrong: it leaves the pipeline outcome-only,
so the skill-bypass question stays anecdotal, and run-loop, aggregation, caching and reporting
stay hand-written — exactly the commodity code we have repeatedly got wrong. **This remains the
fallback if the spike fails.**

**Inspect AI.** UK AISI framework with first-class sandboxes, tool use, and a `Task(dataset,
solver, scorer)` model whose scorers may execute commands inside the sandbox — genuinely close to
outcome grading, and designed for agentic evaluation rather than adapted to it. Rejected because
driving `copilot --agent … --plugin-dir …` would still be a custom solver (so the domain glue is
not reduced relative to DeepEval), because it has no equivalent of `ToolCorrectness` against
`expected_tools` without custom scoring, and because it is the larger conceptual bet to import in
place of code we have just finished debugging. Worth revisiting if multi-epoch sampling or
statistical significance become requirements.

**Keep the harness as-is.** Rejected: it neither answers trajectory questions nor addresses the
twin duplication, and the defects found on 2026-08-19 show the status quo is not stable.

## References

- [ADR 0014](0014-skill-evaluation-with-waza.md) — skills-layer decision this complements;
  not superseded, the two layers stay on different tools.
- [ADR 0008](0008-layered-evaluation-strategy.md) — the layered evaluation strategy this extends.
- `eval/README.md` — layer taxonomy and acceptance-criteria rules.
- `plugins/agile-agents-core/skills/acceptance-grading/SKILL.md` — owns grading doctrine
  regardless of host framework.
- DeepEval metrics — https://deepeval.com/docs/metrics-introduction
- DeepEval LLM tracing — https://deepeval.com/docs/evaluation-llm-tracing (trajectory metrics
  require tracing; this is the integration gap the adapter fills)
- DeepEval custom metrics — https://deepeval.com/docs/metrics-custom (`BaseMetric` permits
  self-coded, non-LLM scoring, so build/test execution survives the move)
- Inspect AI — https://inspect.aisi.org.uk/

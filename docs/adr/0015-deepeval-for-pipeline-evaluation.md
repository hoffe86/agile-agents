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

The enabling fact was established by inspecting a real run log, not assumed: **Copilot CLI's `-s`
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

# ADR 0012 — Add a `data-scientist` agent carrying both evaluation rubrics; a negative result is a completed task

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (roster extension)
- **Related:** ADR 0009 (author owns its own verification), ADR 0010 (review lens split), ADR 0007 (`model_tier`)
- **Reference studied:** [`microsoft/hve-core/.github/agents/data-science`](https://github.com/microsoft/hve-core/tree/main/.github/agents/data-science)

## Context

The suite had no role for work whose deliverable is a **conclusion** rather than a feature:
exploratory analysis, data quality assessment, experiments, models, and the evaluation of
AI-integrated features. Those tasks were reaching `coding`, which owns Python and even owns
AI-surface safety (`development-practices` §8 — prompt injection, OWASP LLM Top 10) but has
no statistical rubric. A leaked split, a missing baseline or a metric averaged the wrong way
is invisible to every gate the suite currently runs: the code builds, the tests pass, the
notebook produces a number, and the number is confidently wrong.

`microsoft/hve-core` was studied as prior art. It ships **five task-scoped, write-capable
agents** — `eval-dataset-creator`, `gen-data-spec`, `gen-jupyter-notebook`,
`gen-streamlit-dashboard`, `test-streamlit-dashboard` — with no shared skills. Two properties
of it shaped this decision:

- Its evaluation agent targets **LLM/agent output quality** (Intent Resolution, Groundedness,
  Task Adherence, Harmful Content, Fairness) against Azure AI Foundry and Copilot Studio. It
  contains no classical-ML machinery: no train/test split, no holdout, no model metrics.
- Its stack coupling is deep and sometimes project-specific — Plotly, Streamlit, uv,
  Playwright, and in one agent hard-coded row counts from a Home Assistant IoT dataset.

## Decision

**One role-scoped `data-scientist` agent in `agile-agents-core`, write-capable, carrying two
evaluation rubrics**, plus one technology-neutral skill `data-science-practices`.

1. **Role-scoped, not task-scoped.** HVE's five agents are tasks (`gen-X`, `test-X`); this
   suite is organised by engineering role. Importing that shape would add five agents that
   overlap `coding` and would have to be re-wired into the pipeline five times.
2. **Both rubrics, routed by what the project builds.** Classical ML (train/test/holdout,
   leakage, calibration, drift, cohort fairness, metric choice) *and* AI/LLM (evaluation-set
   design, groundedness, task adherence, LLM-as-judge validation, RAI risk-to-metric mapping).
   HVE covers only the second; a project doing churn prediction and one doing a RAG assistant
   both need this role and the metrics do not transfer.
3. **Stack depth is deferred, not shipped.** pandas / Plotly / notebook / Streamlit
   conventions are Python-coupled and optional, so by the repo's own plugin rule they belong
   in a companion (`agile-agents-datascience`) — and by *no speculative generality*, that
   plugin is not created until a real project needs it. The agent routes on skill
   availability and falls back to repo conventions, saying so in its hand-off.
4. **The data/engineering boundary mirrors infrastructure's.** `data-scientist` owns the model
   and its evidence; `coding` owns the application that serves it, including the serving path
   and error handling. A task needing both is two tasks, joined by the hand-off's
   `Interface for coding` field.
5. **`ANALYSIS COMPLETE` is a new sentinel block**, and its `Outcome` field is three-valued:
   ✅ supported, ⚠️ inconclusive, ❌ not supported.
6. **`data_science.*` profile keys** are added to the template in the same change, per the
   contract rule. `enabled: false` is the default; when false the agent declines rather than
   improvising a stack.

### The gate change that makes this work

**A negative result is a passing task.** Stage 6's gate assumed a completed task produces a
working diff. An analysis task answers a question, and *no* is a legitimate answer — often the
most valuable one, since it is cheapest before anyone builds on the premise. So:

- All three outcomes pass the gate when the evidence supports them.
- **`dev-lead` is explicitly forbidden from sending a corrective round to ask for a better
  result.** That would be instructing an agent to keep trying until the data agrees, which is
  how a run manufactures a false positive.
- A ✅ is gated *harder* than a ❌: it must name a baseline and beat it, report uncertainty,
  and state the split rule, seed and leakage checks.
- A ⚠️/❌ that invalidates a dependent task's premise fires stop condition #3 (scope change)
  rather than proceeding to build on a disproved assumption.

### Guardrails adopted from HVE

Four of its patterns were better than anything the suite had, and were generalised:

- **`validation_status` on generated datasets** (`ai-generated` | `expert-reviewed` | `mixed`)
  — epistemic status carried in the data's own metadata, so a later reader cannot mistake a
  generated set for ground truth.
- **"A risk with no detecting metric is an unmeasured risk; state it explicitly rather than
  omitting the row"** — an omitted row reads as an absent risk.
- **Population as its own axis**, never folded into a difficulty rating, preserving the
  ability to ask "does this work worse for group X?".
- **Synthesise, never reproduce** a real record — a prohibition with a positive alternative
  rather than a caution.

## Consequences

**Positive**
- Data work has an owner with the right rubric, and an autonomous run no longer routes it to
  an agent that lacks one.
- A negative result is representable. Previously the pipeline had no way to record "we asked,
  and the answer is no" as anything but a blocked task.
- The privacy rule is enforced at the role that touches data first, with a profile-declared
  policy behind it.
- The suite gains a `heavy`-tier author — justified because the failure mode is silent: a
  wrong metric or a leaked split produces a confident number, not an error.

**Negative**
- **No review lens covers statistical validity.** `code-reviewer` judges the code craft and
  `security-reviewer` the data handling, but leakage, baseline honesty, metric choice and
  cohort bias are checked by nobody. Under ADR 0009's "author owns its own verification" this
  leaves `data-scientist` with *less* independent scrutiny than `coding` has — `coding` at
  least has `test-reviewer`. **Mitigated, not solved:** the hand-off carries a mandatory
  `Unreviewed dimensions` field and `review-lead` must reproduce it verbatim under its own
  heading in the merged report, so a ✅ verdict cannot be misread as validation of the
  conclusion. The real fix is a sixth lens (`data-reviewer`); it is deliberately deferred
  rather than bundled, and this is the first place to look when this agent's output is
  trusted too readily.
- One more agent (14) and one more sentinel to keep consistent across the event enum, tier
  tables and generated docs.
- The two rubrics make this a large skill. It is one skill rather than two because the
  discipline that matters most — question first, baseline, uncertainty, leakage, cohorts,
  reproducibility, privacy — is shared, and only the metric catalogue differs.

## Alternatives considered

- **Port HVE's five agents.** Rejected: task-scoped shape conflicts with this suite's roles,
  and the stack coupling (Plotly/Streamlit/uv, and one project-specific dataset) would arrive
  with them.
- **Extend `coding` with a data rubric.** Rejected: `coding` is already `mid`-tier and carries
  two skills; the judgement here is `heavy`, and merging them would repeat the mistake ADR
  0010 undid — one agent whose second job silently degrades.
- **Standalone agent, outside the pipeline.** Considered seriously and rejected: an autonomous
  run that hits data work would hand it to `coding` anyway, which is precisely the silent
  degradation this ADR exists to prevent.
- **Add `data-reviewer` in the same change.** Rejected for scope discipline, and recorded
  above as the known gap with its mitigation.
- **Ship the Python/notebook skills now.** Rejected as speculative generality; the companion
  plugin is a follow-up when a project needs it.

## References

- `plugins/agile-agents-core/agents/data-scientist.agent.md`
- `plugins/agile-agents-core/skills/data-science-practices/SKILL.md`
- `plugins/agile-agents-core/agents/dev-lead.agent.md` (Stage 6 routing; the negative-result gate)
- `plugins/agile-agents-core/agents/review-lead.agent.md` (the unreviewed-dimensions carry-through)
- `.../solution-profile-interview/references/solution-profile.template.yaml` (`data_science.*`)

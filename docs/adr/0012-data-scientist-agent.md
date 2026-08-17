# ADR 0012 — Add data capability: a `data-scientist` author, a `data-reviewer` lens, data-engineering practices, and data-aware Research and Plan

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
evaluation rubrics** — plus a `data-reviewer` lens that independently checks its conclusions,
a second technology-neutral skill (`data-engineering-practices`) giving pipeline work an owner
with a rubric, and data questions made explicit in the Research and Plan phases.

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

### `data-reviewer` — the lens that checks the conclusion

Under ADR 0009 an author owns its own verification, and the counterweight is an independent
reviewer. `coding` has `test-reviewer`; `data-scientist` had nobody, which would have left the
suite's *least* self-checkable output with its *least* scrutiny. This class of defect is
invisible in the output: broken code throws, but a leaked split returns a confident,
well-formatted number that a reader will act on.

So a sixth lens joins the review fan-out, read-only and `heavy`-tier, judging **the conclusion
rather than the craft** — leakage and holdout contamination, split design, baseline presence,
metric choice and averaging convention, uncertainty and multiplicity, cohort fairness,
reproducibility, dataset provenance and epistemic status, committed PII, and for AI features
evaluation-set coverage and LLM-as-judge validity. `review-lead` triages it on any diff
touching analysis, model or evaluation artifacts, and forwards the `ANALYSIS COMPLETE` block
so the lens can check the **claim against the evidence** rather than taking either on trust.

Two rules keep it honest: it **never grades the direction of a conclusion** (a rigorous ❌ is a
pass — findings attach to method, not to whether the answer was welcome), and it **never
re-runs an experiment or re-fits a model**. An unreproducible result is a 🟠 Major finding, not
an invitation to reconstruct the work.

### Data engineering — Research and Plan, and who implements

Making Research and Plan data-aware would have been half a change on its own: surfacing data
tasks without an owner for them just relocates the silent mis-routing this ADR exists to
prevent. So both land together.

- **Research (`architect`)** answers, read-only: does the source exist, may we use it, is it fit
  for purpose, what is its contract, where does it physically land, and what must be settled by
  analysis before building. Results return as `Data findings` and `Data questions to answer
  before building`. A missing source or unpermitted personal-data dependency is a **Stage 1
  blocker**, taken to the human before tasks are planned on top of it.
- **Plan (`dev-lead`)** makes a feasibility question its own task, sequenced first, and states
  at the approval gate which tasks die if it returns ❌ — the moment a human can cheaply pick a
  different approach. Bundling a feasibility check into the model task is explicitly forbidden:
  a ❌ would arrive entangled with half-built code, and the gate could not distinguish a clean
  negative result from a failed implementation.
- **Implementation** is split rather than given a new agent: transformation logic → `coding`,
  platform and orchestration → `infrastructure`, semantics and fitness → `data-scientist`. All
  three load `data-engineering-practices`, whose governing principle is **fail loudly, never
  silently** — a job that crashes is fixed within the hour; a job that quietly writes wrong data
  corrupts every downstream consumer and is found weeks later.

No `data-engineer` agent was added. The work divides cleanly along an existing seam, and a
shared skill gives each side the rubric it lacked without a fifteenth role.

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
- **Two more agents (15) and one more sentinel** to keep consistent across the event enum,
  tier tables and generated docs. A seventh review agent also means one more dispatch on any
  diff containing data artifacts — the lens is triaged, not unconditional, so a diff with no
  analysis in it pays nothing.
- **`data-reviewer` cannot verify what was never committed.** It reads artifacts; a result
  produced in an external notebook, a managed workspace or an experiment tracker is
  unverifiable from the diff. That is reported as a 🟠 Major finding rather than assumed
  sound — but it means the lens is only as strong as the project's habit of committing its
  evidence.
- **Two large practice skills now sit in core.** They are technology-neutral, so every project
  carries them whether or not it does data work. `data_science.enabled` lets the agent decline
  outright, but the skills themselves are still in the matching pool.
- **The data/engineering split is a judgement call at planning time.** "Transformation logic vs
  platform vs semantics" is obvious in the common cases and genuinely ambiguous in others (a
  dbt model carrying business logic in SQL). `dev-lead` decides, and a wrong call costs a
  hand-off.
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
- **Defer `data-reviewer`.** Initially chosen for scope discipline, then reversed: deferring it
  would have shipped an author whose output nothing checks — the exact failure this suite keeps
  finding elsewhere. The lens is cheap (read-only, parallel, triaged onto data diffs only); the
  gap was not.
- **Add a `data-engineer` agent.** Rejected: the work divides along an existing seam —
  transformation logic is application code, platform is infrastructure — and a shared skill
  gives both sides the rubric they lacked without a fifteenth role.
- **Ship the Python/notebook skills now.** Rejected as speculative generality; the companion
  plugin is a follow-up when a project needs it.

## References

- `plugins/agile-agents-core/agents/data-scientist.agent.md`
- `plugins/agile-agents-core/skills/data-science-practices/SKILL.md`
- `plugins/agile-agents-core/agents/dev-lead.agent.md` (Stage 6 routing; the negative-result gate)
- `plugins/agile-agents-core/agents/review-lead.agent.md` (the unreviewed-dimensions carry-through)
- `.../solution-profile-interview/references/solution-profile.template.yaml` (`data_science.*`)
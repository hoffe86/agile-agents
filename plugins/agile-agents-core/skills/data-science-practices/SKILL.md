---
name: data-science-practices
description: >-
  The craft bar for data work — question-before-method discipline, data quality
  and provenance, leakage and split hygiene, baselines, uncertainty, cohort
  fairness, reproducibility, and PII/synthetic-data rules. Carries **two
  evaluation rubrics** and routes between them by what the project is building:
  classical ML (train/test/holdout, calibration, drift, metric choice) and
  AI/LLM (evaluation-set design, groundedness, task adherence, LLM-as-judge
  caveats, responsible-AI risk-to-metric mapping). Technology-neutral: names no
  library and assumes no platform. Loaded by the `data-scientist` agent on every
  task. USE FOR: analysing data, designing an experiment, choosing metrics,
  building or evaluating a model, designing an evaluation set for an AI feature.
  DO NOT USE FOR: writing the production application that serves a model (that
  is `development-practices`), or reviewing someone else's diff.
applies_to: all
---

# Data-science practices

The bar for work whose output is a **conclusion** rather than a feature. A conclusion is
wrong in ways code is not: it compiles, it runs, it produces a number, and the number is
confidently incorrect. Nothing downstream will catch it, which is why the discipline below
sits in the method rather than in a test.

`engineering-standards` applies to the code you write and is not restated here.
`development-practices` covers that code's craft. This skill covers the reasoning.

## 1. The question comes first

Before choosing a method, write down:

- **The question**, in one sentence, with the population it applies to.
- **The decision it informs.** If no decision changes on the answer, stop and ask why the work
  is being done.
- **What would count as an answer** — including what result would mean *don't build this*.

Deciding the "don't build this" threshold **before** seeing results is what makes a negative
result reportable rather than negotiable. Afterwards, every threshold is arguable.

**"No" is a deliverable.** Signal absent, sample too small, labels unreliable, effect
indistinguishable from noise — each is a finding that saves the cost of building on sand.
Report it early, plainly, with the evidence, and without hedging it into ambiguity.

## 2. Know the data before you model it

- **Provenance.** Where did it come from, who owns it, what may it be used for, and how current
  is it? A dataset with no answer to "may we use this?" is blocked, not merely awkward.
- **Profile from a bounded sample**, not the full table: schema, types, cardinality,
  missingness, ranges, obvious impossibilities (negative ages, future timestamps, duplicated
  keys).
- **Missingness is information.** Establish whether values are missing at random or
  systematically — the latter is usually a finding about the collection process, and imputing
  over it hides a defect.
- **Check the label as hard as the features.** Where does it come from, how is it defined, how
  often is it wrong, and could it have been derived from something you are also feeding in?

## 3. Leakage — assume it until you have excluded it

Most implausibly good results are defects. Before believing a number, check:

- **Target leakage** — a feature computed from, or downstream of, the label.
- **Temporal leakage** — training on records that postdate the prediction point; any time-series
  split must respect time order.
- **Group leakage** — the same entity (user, device, patient, document) appearing in both
  train and test.
- **Preprocessing leakage** — scaling, imputation, encoding or feature selection fitted on the
  full dataset before splitting.
- **Duplicate leakage** — near-duplicate rows straddling the split.

**Split first, then explore.** Once you have looked at the holdout, it is no longer a holdout.
If that happens, say so and re-split — quietly continuing invalidates every number that follows.

## 4. Baselines and uncertainty

- **Always report against a trivial baseline**: majority class, mean/median, last value, the
  existing business rule, or the current human process. A model that cannot beat it is a
  negative result.
- **Report a spread, not a point.** A confidence interval, cross-validated variance, or at
  minimum the sample size the metric was computed on. State how much of any difference could be
  noise.
- **Beware the multiplicity trap.** Try twenty configurations and one will look significant by
  chance. Say how many things you tried.
- **A difference that is statistically significant may be operationally irrelevant.** Report the
  effect size in units the decision-maker cares about, not only the p-value.

## 5. Choosing metrics (both rubrics)

The wrong metric is the most common silent failure in this work. Choose it from the decision,
and state its averaging convention explicitly — macro, micro and weighted averages disagree,
often dramatically, on imbalanced data.

### Classical ML

- **Imbalanced classification** — accuracy is misleading; prefer precision/recall, PR-AUC, or a
  cost-weighted measure. State the operating threshold and why.
- **Ranking / retrieval** — report at the k the product actually uses.
- **Regression** — pick error units the reader can interpret; report whether errors are biased
  in one direction.
- **Probabilities that drive decisions must be calibrated**, not merely ordered correctly.
- **Drift** — for anything running in production, state what will be monitored (input
  distribution, prediction distribution, realised outcomes) and what change should trigger a
  human look.

### AI / LLM features

- **The evaluation set is the deliverable**, and it is designed, not collected by convenience.
  Cover the intended tasks, the realistic failure modes, adversarial inputs, and every user
  population the feature serves.
- **Population is its own axis** — never fold it into a difficulty rating, or you lose the
  ability to ask "does this work worse for group X?".
- **Common dimensions**: does it resolve the user's intent; is it grounded in the provided
  sources (and does it say so when it isn't); does it adhere to the task and format; does it
  call tools correctly; does it refuse when it should; is the output free of harmful content.
- **LLM-as-judge is a measurement instrument and needs its own validation.** Report agreement
  with human judgement on a sample before trusting it at scale, and never judge with the same
  model and prompt that produced the output.
- **Declare epistemic status in the dataset's own metadata**: `ai-generated` until a domain
  expert reviews it, then `expert-reviewed`, or `mixed`. A generated set presented as ground
  truth will be believed by someone who wasn't there.

### Responsible AI — risk to metric

Map each identified risk to the metric that would detect it. **A risk with no detecting metric
is an unmeasured risk: state it explicitly rather than omitting the row.** An omitted row reads
as an absent risk; a declared gap reads as a decision someone can act on.

## 6. Fairness and cohorts

Any model or AI feature that affects people is reported **broken down by the populations it
affects**, not in aggregate only. Aggregate performance routinely hides a cohort the system
fails.

- Choose cohorts from the domain and any legal obligations, not from what is convenient to
  compute.
- Where a cohort is too small to measure reliably, say so — that is itself a finding about
  coverage.
- Where cohort attributes are unavailable, state that the fairness question is **unmeasured**
  rather than implying it was checked.

## 7. Reproducibility

A result nobody can re-run is an opinion. Record, in the artifact itself:

- the **seed** and anything else non-deterministic (including model/API version for LLM work,
  where identical inputs need not give identical outputs — say how many runs you averaged);
- the **data version** or snapshot date, and the exact filter/query;
- the **split rule**;
- the **environment** — dependency versions pinned the way the repo already pins them;
- the **command** that re-runs it end to end.

Parameterise paths; never commit an absolute path from your machine. Prefer an artifact that
runs top to bottom without manual edits — that is a binary, checkable bar.

## 8. Privacy and synthetic data

- **Never reproduce a real personal record** in a notebook output, evaluation set, fixture,
  prompt, test, or commit. When you need examples, **synthesise** them — a rule with a positive
  alternative, not a caution.
- **Committed previews are leaks.** Keep sample values out of committed artifacts, or bound
  them tightly and confirm they are non-identifying.
- Honour the project's declared policy (`solution-profile.yaml: data_science.data_privacy.pii_policy`,
  `ai_copilot.pii_handling_rule`). If it is unstated and the data looks personal, stop and ask;
  absence of a rule is not permission.
- Aggregates can re-identify. Small-cell counts in a published breakdown are a disclosure risk.

## 9. Handing a model to engineering

When a model ships, the deliverable is not the weights — it is the **contract**:

- inputs and outputs, with types, units and ranges;
- what it does when it cannot answer confidently (abstain, fall back, return a default) —
  decided by you, implemented by `coding`;
- known failure modes and the populations most affected;
- latency and resource profile;
- what to monitor, and what change should trigger retraining or a human review;
- the model card / summary a future maintainer needs to understand what it is for.

`coding` owns the serving path, error handling and integration. If you find yourself writing
the application, the task needs splitting.

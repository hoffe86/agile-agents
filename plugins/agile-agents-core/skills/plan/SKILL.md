---
name: plan
description: >-
  Plan phase of Research → Plan → Implement, usable by any agent: decompose a
  requirement into traceable, independently implementable tasks, map
  acceptance criteria and dependencies, make data work explicit and prepare a
  tracker or inline plan for human approval. States the phase purpose,
  outcome, rules, quality bar and exit gates. An orchestrator such as dev-lead
  keeps approvals, transitions, stops and retry budgets.
metadata:
  applies_to: all
---

# Plan phase

## Purpose

Turn verified research into the smallest set of tasks a human can approve and
an author can deliver one at a time. Plan decides *what* gets built and in
which order; it does not build, and it does not approve itself.

Typical users: `dev-lead` (Stages 2–5), `backlog-manager` (materialising tasks)
and any agent asked to break work down.

## Outcome

A plan ready for human approval:

- tasks, each with an imperative title, testable acceptance criteria and a
  self-contained approach note;
- every requirement acceptance criterion mapped to task id(s) or marked
  `out-of-scope` with a reason;
- ordering constraints between tasks;
- assumptions, risks, trade-offs and feasibility-dependent work, visible;
- tracker children linked to the parent, or the same plan inline.

## Rules

- No implementation before approval. Planning does not authorise writes to
  source, tests or IaC.
- Never grow scope. Out-of-scope ideas become follow-ups.
- Adopt a supplied plan; reconcile every source step as carried, merged or
  dropped rather than silently re-deriving it.
- Never bundle feasibility analysis with a model task.
- This skill does not interpret an approval response or decide to advance.

## Quality bar

- Fewest meaningful tasks; prefer vertical slices that deliver observable value.
- Highest uncertainty first; dependent work is marked provisional.
- Each approach note names components or files, applicable patterns and
  decisions, in-scope and out-of-scope work, and material assumptions.
- Use Gherkin when `tech_stack.test_discipline` is `bdd`.

## Exit gates

The phase is complete only when all hold:

1. Every requirement criterion is covered or explicitly out-of-scope.
2. Every `architect` follow-on task and every source-plan step is accounted for.
3. Every ordering constraint is recorded.
4. When tracker tasks are enabled, each child is created and linked to the
   required parent; a write failure stops the phase.
5. A human approved the plan, and any required design approval.

The caller enforces these gates. Under `dev-lead`, `dev-lead` alone owns stage
transitions, tracker delegation, approval handling and entry to Implement.

## Working method

Produce the smallest meaningful set of independently implementable tasks.
Combine work that always ships together; keep an uncertainty-resolving task
small and early. Check inexpensive facts before turning assumptions into
approach instructions.

Map every requirement acceptance criterion to its delivering task. Record
ordering in `todo_deps` and per-task applicability: design/docs and
non-behavioural configuration may not need application tests; IaC and its
tests belong to `infrastructure`. Review always applies. The local task cache
is not authoritative when it conflicts with the tracker.

Make data ownership explicit. A `data-scientist` feasibility task may
legitimately return no; sequence it before dependent work. Ownership:
transformation logic belongs to `coding`; platform/storage/orchestration
belongs to `infrastructure`; data semantics, analysis, modeling and evaluation
belong to `data-scientist`. Join producer and consumer with a dataset contract
stating grain, keys, schema and freshness. A missing required source or
unpermitted personal data is a scope question, not a decomposition problem.

When `backlog.create_tasks` is enabled, send `backlog-manager` each task, the
Research approach summary and the relevant `backlog.*` and
`team_communication.code_language` subset; each child is linked to the
required parent. When disabled or `backlog.platform` is `none`, keep the plan
inline. Under `dev-lead`, use `dev-lead-templates` for the task-creation recipe,
approval prompts and output shapes.

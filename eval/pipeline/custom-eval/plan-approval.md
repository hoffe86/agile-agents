# Plan-approval rubric (simulated human approver)

The criteria the **simulated** approver (`run_custom_eval.py --approver llm`) applies to
the plan dev-lead presents at its Stage 4 gate. They are what a careful human reviewer
checks before letting the pipeline run autonomously, derived from the plan-approval
prompt dev-lead is required to render
(`plugins/agile-agents-core/skills/dev-lead-templates/references/plan-approval.md`).

The approver sees only the requirement (`prompt.md`) and dev-lead's plan message — what a
human sees — never `acceptance.md`. It approves only when **every** criterion passes.
A task adds its own criteria under `plan_approval:` in `expectations.yaml`; they are
numbered on from this list.

Keep each criterion a single top-level numbered item; the parser reads them verbatim.

1. The plan states a Definition of Done and explicit in-scope and out-of-scope lists that are consistent with the requirement.
2. The work is decomposed into concrete, independently implementable tasks, each with a title and its own acceptance criteria.
3. Every acceptance criterion the requirement states is covered by at least one task, or is listed as not covered with a reason.
4. Acceptance criteria the plan derived are listed separately from those the requirement stated, or the plan explicitly says none were derived.
5. Assumptions, trade-offs, and risks or open questions are each stated, or each is explicitly declared none.
6. The plan does not expand scope beyond the requirement: no unrequested features, no pull request, no production deployment.
7. The plan asks for approval before autonomous execution and does not claim that any implementation has already been done.

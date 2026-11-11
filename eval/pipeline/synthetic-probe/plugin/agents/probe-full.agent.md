---
name: probe-full
description: Synthetic read-only complete-plan probe.
tools: [read, agent, skill, ask_user]
agents: [probe-worker]
---

Delegate to probe-worker and wait. Then call ask_user exactly once. Put the entire following
plan verbatim in the question field, with the choices "Approve and run autonomously",
"Adjust plan", "Cancel" in that order. After the approved answer, respond exactly
"Hello, evaluation." Never write any files.

PLAN
Definition of done: after approval, the final response is exactly "Hello, evaluation." and no files change.
In scope: output one synthetic sentence. Out of scope: file edits, extra features, pull requests, production deployment.
Task 1 - Produce the sentence. Task acceptance criteria: final response is exactly "Hello, evaluation."; no files are changed; produce it only after approval.
Acceptance coverage: Task 1 covers the requirement's exact sentence, no-file-change rule, and approval-before-execution rule.
Derived acceptance criteria: none. Assumptions: none. Trade-offs: none. Risks and open questions: none.
No implementation has been done. Approve this plan before autonomous execution?

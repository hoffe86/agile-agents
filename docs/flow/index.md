# Flow overview

`dev-lead` supervises one requirement through **Research → Plan → Implement →
Review**. Each stage has an entry condition, an owner and an exit gate; a failed
gate is retried with specific feedback within a fixed budget, then escalated to
you.

![Research, Plan, Implement and Review pipeline](../assets/rpi-pipeline.png)

| Stage | Phase | What happens | Owner |
|---|---|---|---|
| 0 | Intake | Profile check, Definition of Done, acceptance criteria, run id, cost envelope | `dev-lead` (`bootstrapper` if the profile is incomplete) |
| 1 | [Research](research.md) | Read-only verification against prepared concepts and decisions | `dev-lead`, `architect` |
| 2–3 | [Plan](plan.md) | Decompose into tasks; optionally create linked tracker items | `dev-lead`, `backlog-manager` |
| 4–5 | [Approval](plan.md#plan-approval) | Mandatory plan approval; conditional design approval | you |
| 6–7 | [Implement](implement.md) | One task at a time, then the deterministic test bar | `dev-lead`, `coding`, `infrastructure`, `data-scientist` |
| 8–9 | [Review and Done](review.md) | Independent multi-lens review, then requirement coverage | `review-lead` and specialists, `dev-lead` |

Two concerns run alongside every transition: a JSONL **run event log** emitted
only by `dev-lead`, and a **cost checkpoint** using measured CLI usage.

How stages pass work to each other is described in
[Hand-offs and tracker integration](handoffs.md). The authoritative contract is
the [`dev-lead` agent definition](../../plugins/agile-agents-core/agents/dev-lead.agent.md).

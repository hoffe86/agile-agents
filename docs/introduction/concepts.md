# Concepts and roles

The harness ships **15 agents** and a set of technology-neutral skills. Each
agent has a narrow role contract; the boundaries matter more than the count.

## Roles

| Group | Agents | Responsibility |
|---|---|---|
| Supervisor | `dev-lead` | Drives one requirement through the pipeline, enforces gates, carries context between stages and reports one Definition-of-Done verdict. It never reviews its own work. |
| Authors | `architect`, `coding`, `infrastructure`, `data-scientist` | `architect` verifies designs (read-only, never writes ADRs). `coding` and `infrastructure` deliver code or IaC **and the tests that cover it**. `data-scientist` owns analysis, models and their evidence. |
| Reviewers | `review-lead`, `code-reviewer`, `security-reviewer`, `test-reviewer`, `architecture-reviewer`, `infrastructure-reviewer`, `data-reviewer` | `review-lead` triages and merges findings into one verdict; it performs no lens itself. Code-quality and security lenses always run. |
| Support | `backlog-manager`, `bootstrapper`, `capability-scout` | Tracker writes, one-off solution setup, and proposal-only capability improvement. |

The [repository overview](../../README.md#what-you-get) lists every agent with its
purpose, and each definition lives under
[`plugins/agile-agents-core/agents/`](../../plugins/agile-agents-core/agents/).

## Core ideas

**Solution profile.** `.github/solution-profile.yaml` is the operational
contract every agent reads: languages, test discipline, tracker, quality-gate
commands, cost envelope. Six fields are required before a run can start.

**Prepared decisions.** Architecture concepts and accepted decision records are
written up front by humans. Agents cite them, conform to them and report
*decision gaps*; they never author ADRs.

**Hand-off blocks.** Every delegated stage ends with a canonical block such as
`IMPLEMENTATION COMPLETE` or `REVIEW COMPLETE`. A missing or malformed block is a
gate failure, not something the supervisor guesses around. See
[Hand-offs and tracker integration](../flow/handoffs.md).

**Read-only by effect.** All agents use an open tool grant, but reviewers and
`capability-scout` are bound by their role contracts: they never edit files,
mutate state or adopt changes.

**Ownership split.** The harness owns process and role boundaries; your solution
owns technical guidance and commands. See
[customization ownership](../customization-ownership.md).

# Concepts and roles

An **agent** owns work; a **skill** describes how to do it. For example,
`coding` owns an implementation and its tests. It can use `testing-practices`
to choose meaningful assertions, but that skill neither runs a second agent
nor approves the result. A reviewer, not the author, judges the change.

The **host** runs these roles and supplies the tools it has made available.
The **solution profile** describes the repository they are working in: which
tracker to use, what commands to run, and which limits apply. Installing the
plugin gives a team the process, not a preconfigured solution or permission to
act on one.

## Roles

| Group | Agents | Responsibility |
|---|---|---|
| Supervisor | `dev-lead` | Drives one requirement through the pipeline, enforces gates, carries context between stages and reports one Definition-of-Done verdict. It never reviews its own work. |
| Authors | `architect`, `coding`, `infrastructure`, `data-scientist` | `architect` verifies designs (read-only, never writes ADRs). `coding` and `infrastructure` deliver code or IaC **and the tests that cover it**. `data-scientist` owns analysis, models and their evidence. |
| Reviewers | `review-lead`, `code-reviewer`, `security-reviewer`, `test-reviewer`, `architecture-reviewer`, `infrastructure-reviewer`, `data-reviewer` | `review-lead` triages and merges findings into one verdict; it performs no lens itself. Code-quality and security lenses always run. |
| Support | `backlog-manager`, `bootstrapper`, `capability-scout` | Tracker writes, one-off solution setup, and proposal-only capability improvement. |

Use the [agent and skill guide](../codebase/STRUCTURE.md) to choose among
all 15 roles and 25 skills by the question you need answered. It links each
one to its shipped definition. A specialist can also be useful on its own:
reviewing an existing diff is a `review-lead` task, not a new delivery run.

## Core ideas

**Solution profile.** `.github/solution-profile.yaml` is the operational
contract every agent reads: languages, test discipline, tracker, quality-gate
commands, cost envelope. Six fields are required before a run can start.

**Prepared decisions.** Delivery starts from decisions the team already owns:
accepted ADRs where the project uses them, design documents or work items
otherwise. Agents cite them and surface *decision gaps* rather than silently
choosing a new direction. The advisory architect does not write ADRs.

**Hand-offs and gates.** A hand-off reports what a producer found or delivered;
a gate decides whether the next stage may start. For example, a delegated
author returns `IMPLEMENTATION COMPLETE` with behavior-to-test evidence.
That report is not a passing test bar or an independent review. See [who
invokes each gate and what evidence it reads](../flow/index.md#who-enforces-a-gate)
and [what agents hand over](../flow/handoffs.md).

**Read-only by effect.** All agents use an open tool grant, but reviewers and
`capability-scout` are bound by their role contracts: they never edit files,
mutate state or adopt changes.

**Ownership split.** The harness owns process and role boundaries; your solution
owns technical guidance and commands. See
[customization ownership](../customization-ownership.md).

## Read by question

| Question | Guide |
|---|---|
| What gets installed, and how do the parts fit together? | [Plugin architecture](../codebase/ARCHITECTURE.md) and [runtime and tools](../codebase/STACK.md) |
| Who should handle this task, and what guidance is available? | [Agents and skills by purpose](../codebase/STRUCTURE.md) |
| Where do local instructions, tracker writes and external tools fit? | [Authoring conventions](../codebase/CONVENTIONS.md) and [integration boundaries](../codebase/INTEGRATIONS.md) |
| How does a requirement become a verified change? | [Your first requirement](../getting-started/first-requirement.md), [delivery flow](../flow/index.md) and [verification and evaluation](../codebase/TESTING.md) |
| Which guarantees should I **not** infer? | [Operating limits](../codebase/CONCERNS.md) |

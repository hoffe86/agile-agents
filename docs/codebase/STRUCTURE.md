# Agents and skills by purpose

Choose an **agent** when you need an owner for an outcome. Choose a **skill**
when an owner needs a method. The core manifest discovers both in separate,
flat directories. A name here links to the actual definition; availability
does not mean every role loads every skill on every run.

## Who owns the work?

| Agent | Use it for | Boundary or result |
|---|---|---|
| [`bootstrapper`](../../plugins/agile-agents-core/agents/bootstrapper.agent.md) | Set up or repair a solution profile. | Discovers first; proposes changes and installs for approval. Reports whether delivery can start. |
| [`capability-scout`](../../plugins/agile-agents-core/agents/capability-scout.agent.md) | Find gaps or better guidance for this solution. | Recommends with provenance and a verification approach; never adopts or installs. |
| [`backlog-manager`](../../plugins/agile-agents-core/agents/backlog-manager.agent.md) | Write or improve tracker items; turn a proposed plan into linked, provisional tasks for human approval. | Owns tracker writes, not priorities or the decision that delivery is complete. |
| [`dev-lead`](../../plugins/agile-agents-core/agents/dev-lead.agent.md) | Deliver one prepared requirement through Research, Plan, Implement and Review. | Coordinates decisions and evidence. May author an approved application or IaC task, never its own review. |
| [`architect`](../../plugins/agile-agents-core/agents/architect.agent.md) | Verify constraints, compare designs and expose decisions the team must make. | Advisory; provides a design or a read-only contribution, not production edits or a new ADR. |
| [`coding`](../../plugins/agile-agents-core/agents/coding.agent.md) | Implement application behavior, refactor or repair a defect. | Owns the change **and** its tests, including the application that serves a model. |
| [`infrastructure`](../../plugins/agile-agents-core/agents/infrastructure.agent.md) | Change IaC, container definitions or delivery pipelines. | Owns IaC validation and tests; does not hand them to the application author. |
| [`data-scientist`](../../plugins/agile-agents-core/agents/data-scientist.agent.md) | Test feasibility, analyze data, fit a model or evaluate an AI feature when enabled. | Delivers method, evidence, uncertainty and an interface where needed. A negative result is legitimate. |
| [`review-lead`](../../plugins/agile-agents-core/agents/review-lead.agent.md) | Review a diff across the applicable disciplines. | Selects independent reviewers and combines their findings into one verdict; performs no lens itself. |
| [`code-reviewer`](../../plugins/agile-agents-core/agents/code-reviewer.agent.md) | Check correctness, regressions, readability and conformance. | Always participates in a delivery review, including docs-only changes. |
| [`security-reviewer`](../../plugins/agile-agents-core/agents/security-reviewer.agent.md) | Check changed content for secrets and security risks. | Always participates; no remediation edits. |
| [`test-reviewer`](../../plugins/agile-agents-core/agents/test-reviewer.agent.md) | Judge testable changes, coverage and modified assertions. | Decides independently whether the author's test-change justification holds. |
| [`architecture-reviewer`](../../plugins/agile-agents-core/agents/architecture-reviewer.agent.md) | Assess boundary, contract and decision alignment on architectural or broad changes. | Reviews the resulting diff, not the design it wishes had been implemented. |
| [`infrastructure-reviewer`](../../plugins/agile-agents-core/agents/infrastructure-reviewer.agent.md) | Review IaC, pipeline and container changes. | Examines deployment safety and provider constraints without provisioning resources. |
| [`data-reviewer`](../../plugins/agile-agents-core/agents/data-reviewer.agent.md) | Judge whether an analytical result or reported metric is supported. | Checks leakage, baselines, uncertainty and reproducibility; does not re-fit a model. |

## Which skill answers my question?

| Question or moment | Core skill and use |
|---|---|
| Where do solution-specific rules come from? | [`read-repo-context`](../../plugins/agile-agents-core/skills/read-repo-context/SKILL.md) discovers scoped instructions, profile constraints, available guidance and binding decisions. |
| Can I decide this myself? | [`engineering-judgement`](../../plugins/agile-agents-core/skills/engineering-judgement/SKILL.md) distinguishes reversible local choices from consequential decisions needing a human. |
| How do we configure this repository? | [`solution-profile-interview`](../../plugins/agile-agents-core/skills/solution-profile-interview/SKILL.md) discovers known values, asks for missing facts and generates portable guidance from the approved profile. |
| Which additional guidance would help? | [`artifact-coverage`](../../plugins/agile-agents-core/skills/artifact-coverage/SKILL.md) compares candidates with what is already available; the result is a proposal, not an installation. |
| I need a map of an entire codebase. | [`acquire-codebase-knowledge`](../../plugins/agile-agents-core/skills/acquire-codebase-knowledge/SKILL.md) is for explicit onboarding or documentation, not routine implementation. |
| I need relevant files for one change. | [`code-localisation`](../../plugins/agile-agents-core/skills/code-localisation/SKILL.md) narrows the search using the solution's configured backend and a local structural option. |
| Where does an architectural decision belong? | [`architecture-decision-records`](../../plugins/agile-agents-core/skills/architecture-decision-records/SKILL.md) structures a record **on explicit human request** in a write-capable context; it does not give an advisor write authority. |
| What makes a tracker item ready? | [`backlog-item-standards`](../../plugins/agile-agents-core/skills/backlog-item-standards/SKILL.md) defines item content and acceptance criteria, not the tracker's API. |
| What must be true before we plan? | [`research`](../../plugins/agile-agents-core/skills/research/SKILL.md) verifies facts and makes assumptions, risks and discipline input explicit. |
| How do we turn criteria into work? | [`plan`](../../plugins/agile-agents-core/skills/plan/SKILL.md) maps criteria to tasks, dependencies and verification approaches for approval. |
| How does an approved task get delivered? | [`implement`](../../plugins/agile-agents-core/skills/implement/SKILL.md) keeps one author accountable for a task, its tests and its evidence. |
| How does the lead carry state between stages? | [`dev-lead-templates`](../../plugins/agile-agents-core/skills/dev-lead-templates/SKILL.md) supplies the stage-specific records, approval prompts and completion report; it does not decide transitions. |
| How should I change application behavior? | [`development-practices`](../../plugins/agile-agents-core/skills/development-practices/SKILL.md) guides scoped changes, verification, documentation and safe Git operations. |
| What tests belong with the change? | [`testing-practices`](../../plugins/agile-agents-core/skills/testing-practices/SKILL.md) guides behavior-based tests, deterministic fixtures and justification for changed assertions. |
| How should a service handle external dependencies? | [`cloud-native-patterns`](../../plugins/agile-agents-core/skills/cloud-native-patterns/SKILL.md) covers portable resilience, readiness, observability and API contracts. |
| What should IaC preserve? | [`iac-best-practices`](../../plugins/agile-agents-core/skills/iac-best-practices/SKILL.md) guides identity, state, repeatability and pipeline safety without choosing a provider. |
| What makes a data pipeline trustworthy? | [`data-engineering-practices`](../../plugins/agile-agents-core/skills/data-engineering-practices/SKILL.md) covers data contracts, replay, quality checks and lineage. |
| What supports an analytical conclusion? | [`data-science-practices`](../../plugins/agile-agents-core/skills/data-science-practices/SKILL.md) covers baselines, splits, uncertainty, cohort differences and privacy. |
| Is the combined change ready for reviewers? | [`test-bar-gate`](../../plugins/agile-agents-core/skills/test-bar-gate/SKILL.md) runs the solution's configured checks and records their actual results. |
| Does the change deploy to the permitted dev environment? | [`deploy-verify`](../../plugins/agile-agents-core/skills/deploy-verify/SKILL.md) uses the project's pipeline only on opt-in; it cannot authorize production. |
| What may a reviewer do? | [`reviewer-read-only-rules`](../../plugins/agile-agents-core/skills/reviewer-read-only-rules/SKILL.md) limits actions by their effects even when write-capable tools are visible. |
| I want a whole-repository audit, not a diff review. | [`code-review`](../../plugins/agile-agents-core/skills/code-review/SKILL.md) is the standalone audit. It is **not** the `code-reviewer` agent or an extra lens for `review-lead`. |
| Where are phase and gate events recorded? | [`run-event-log`](../../plugins/agile-agents-core/skills/run-event-log/SKILL.md) defines the supervisor's ordered, append-only record of a run. |
| Has a run or phase exceeded its allowance? | [`cost-budget`](../../plugins/agile-agents-core/skills/cost-budget/SKILL.md) compares measured usage to configured caps; it does not ask agents to estimate spend. |
| Does an evaluation artifact meet a stated criterion? | [`acceptance-grading`](../../plugins/agile-agents-core/skills/acceptance-grading/SKILL.md) distinguishes a demonstrated pass, a demonstrated failure and an unverified claim. It is not PR review. |

**Evidence:** [core discovery paths](../../plugins/agile-agents-core/.github/plugin/plugin.json),
[generated inventory](../../AGENTS.md), [skill provenance](../../plugins/VENDORED.md).

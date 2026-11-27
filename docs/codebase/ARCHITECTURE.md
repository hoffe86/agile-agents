# How the plugin fits together

The unit of delivery is **one prepared requirement in one consuming solution**.
The team supplies the intended outcome, decisions and access. The plugin supplies
roles and a sequence of decisions about the work. It is not a hosted project
management service, a CI runner or a replacement for the team that accepts the change.

## System context

| Part | What it owns | What it does not own |
|---|---|---|
| Marketplace | Discovery of `agile-agents-core` and the independently maintained, optional `agentic-persona`. | Installing core does not install persona or enable personal instructions. |
| Core plugin | Agent definitions, skills, helper scripts, MCP configuration and an optional profile-editing extension. | The consuming solution's framework choices, commands, credentials or production environment. |
| Copilot host | Runs the agent, exposes available tools and presents human interactions. | A tool grant does not authorize its effects. A host without canvas support can still use the profile interview. |
| Consuming repository | Its solution profile, scoped instructions, local skills, accepted decisions, source and tests. | The generated `AGENTS.md` is a portable view, not another profile to maintain. |
| External systems | The team's actual backlog, code host and pipeline, if configured and accessible. | A task status is not verification; a PR is not permission to merge. |

## From requirement to evidence

1. **Prepare.** `bootstrapper` discovers the solution's facts and proposes
   missing configuration. With a ready profile, `dev-lead` records the
   requirement's acceptance criteria and what is out of scope.
2. **Decide.** The author disciplines contribute read-only research and refine
   a task plan. The human approves that plan, including any criteria inferred
   from the requirement. A material design choice can need separate approval.
3. **Produce.** One author at a time works within the approved task boundary.
   Application and IaC authors own their tests. A data task delivers a supported
   conclusion rather than a promise that an experiment will succeed.
4. **Verify.** Before independent review, the lead runs the combined deterministic
   gate or records an applicable skip. A declarative IaC-only diff with
   author-run IaC tests can qualify for a skip; executable IaC does not qualify
   merely because it is infrastructure. The lead reconciles the original criteria
   with delivered evidence. It cannot substitute its own review for theirs.

This is why the plugin separates **four records**. The plan says *what was
agreed*. A hand-off says *what one role is giving the next*. Gate results and
review findings say *what was checked on which content*. Run events and metered
usage say *what happened and what it consumed*. Only criterion-linked delivery
evidence answers *did we build the right thing?*

## Where to go next

Start with [agents and skills](STRUCTURE.md) to select an entry point, or follow
[one requirement through the stages](../flow/index.md). For authority, external
effects and limits, see [integrations](INTEGRATIONS.md) and
[what the evidence cannot prove](CONCERNS.md).

**Evidence:** [core manifest](../../plugins/agile-agents-core/.github/plugin/plugin.json),
[marketplace](../../.github/plugin/marketplace.json),
[supervisor contract](../../plugins/agile-agents-core/agents/dev-lead.agent.md),
[author ownership](../adr/0009-merge-coding-and-testing-agents.md),
[independent review](../adr/0010-split-general-review-lens-from-orchestrator.md),
[specialist participation](../adr/0016-t-shaped-research-and-plan.md).

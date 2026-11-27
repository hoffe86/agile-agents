# Operating limits

These are boundaries to consider when relying on the plugin, not a backlog of
proposed changes.

| If you see… | What you can conclude | What you still need |
|---|---|---|
| An agent, skill or MCP server in a manifest | The plugin declares it for discovery. | A compatible host, actual availability and the necessary permissions. A capability listing is not evidence that a skill was invoked. |
| A read-only review contract | The reviewer is required not to change state. | Host and service access controls where technical isolation is required. A role contract is not a sandbox. |
| A worker hand-off or an event reporting a pass | A producer supplied an account of the work or a milestone was recorded. | Test/check results for the actual content, an independent verdict and evidence for the original criterion. |
| A preferred model or a USD cap | The solution recorded a preference or financial policy. | Native model selection and measured usage. A dollar amount cannot be computed without a rate; a minutes estimate is not a deadline. |
| An offline score or a simulated scenario | Evidence about the input and metric that were actually exercised. | Separate outcome evidence. A simulation cannot stand in for human approval in delivery. |

## Reliability and maintenance

One writer per task makes ownership and corrective retries traceable, at the
cost of sequential implementation. Read-only research and review can fan out;
their calls still consume budget. Local-first code localisation limits the need
for external services but need not find everything a semantic search would.
No throughput, latency or model-equivalence guarantee follows from these choices.

The supervisor contract, role definitions, their hand-off schemas and the
profile readers change together. If one describes different fields, or a
consumer repeats old role counts, a reader may mistake stale guidance for a
current contract. Follow the linked definitions instead of copying them.
Scope and consent questions belong with the consuming team; they cannot be
answered by a scan of the plugin.

**Evidence:** [ownership and permission boundaries](../customization-ownership.md),
[hand-off schemas](../../plugins/agile-agents-core/skills/read-repo-context/references/handoff-contracts.md),
[localisation decision](../adr/0001-code-localisation-backend-default.md),
[budget policy](../../plugins/agile-agents-core/skills/cost-budget/SKILL.md),
[evaluation limits](../../eval/README.md).

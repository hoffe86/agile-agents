# Installation

## Prerequisites

- GitHub Copilot CLI with plugin support.
- A Git repository you can create feature branches in.
- Optionally, access to your work-item tracker if you want tasks created there.

## Install the core plugin

```shell
copilot plugin marketplace add hoffe86/agile-agents
copilot plugin install agile-agents-core@agentic-universe
```

Existing `agile-agents-marketplace` registrations are **not** migrated
automatically to `agentic-universe`.

## Optional personal guidance

The same marketplace lists the independently maintained
[`agentic-persona`](https://github.com/hoffe86/agentic-persona) plugin. It is
never required by the harness:

```shell
copilot plugin marketplace update agentic-universe
copilot plugin install agentic-persona@agentic-universe
```

Personal preferences may add stricter consent, but cannot waive harness
approvals, safety or reviewer boundaries. See
[customization ownership and rollback](../customization-ownership.md) — removing
a catalog listing does not uninstall existing copies.

## Optional model preferences

Model tiers in the profile are advisory. Configure preferred models yourself in
the native `/subagents` UI; the harness never writes user or global settings.
The [manual setup procedure](../../plugins/agile-agents-core/skills/cost-budget/references/tier-defaults.md)
documents version caveats.

Next: [bootstrap the repository](bootstrap.md).

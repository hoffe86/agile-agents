# Customization ownership

Three independent owners compose through the client's native mechanisms:

| Owner | Owns | Delivery |
|---|---|---|
| Harness | Roles, approvals, read-only review, evidence and general execution contracts | `agile-agents-core` |
| Solution | Technology, framework/provider/tracker conventions and actual check commands | Repository/path instructions, local skills and explicitly selected external plugins |
| User | Personal collaboration preferences and stricter consent | Optional native user instructions, skills or a personal plugin |

Core ships no solution recipes or personal defaults. Discover existing sources
before adding anything; match task, path, stack, version, provider and role.
Respect directory/`applyTo` scope and native delivery. Availability does not
prove invocation or automatic injection. Do not invent universal precedence.
Personal preferences cannot waive solution constraints, approvals or safety.

An optional example is **[agentic-persona](https://github.com/hoffe86/agentic-persona)**.
That repository owns its packaging, activation and verification; it is not a
core dependency. Its native instructions require separate opt-in. No particular
user name, local path or personal package is required.

## Shared marketplace

`agentic-universe`, registered from `hoffe86/agile-agents`, provides shared
discovery for `agile-agents-core` and the optional `agentic-persona` plugin.
Shared discovery keeps installation in one catalog without combining ownership
or implementation.

This repository implements only core, which uses a local plugin source.
Persona is owned and released independently in `hoffe86/agentic-persona` and
listed through an external GitHub source. No persona code or skills are copied
here, and installing core does not install persona.

The marketplace name is a native registration/install identifier, distinct from
repository and plugin names. See the [compatibility note](../README.md#install)
for existing registrations.

The source object uses the
[Copilot CLI marketplace format](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference#marketplacejson).
It targets the external repository root on its default branch, not this
catalog's local `metadata.pluginRoot`. The listing's version describes the
upstream manifest; it is not a commit pin. Review the upstream source before
installing or updating.

The offline version check validates external source shape, not remote
availability or manifest/version agreement. Verify the live upstream manifest
when changing its listing. Local core consistency and per-PR bump checks
apply; catalog-only changes do not bump unchanged core or its matching
marketplace metadata version.

## Install, update and remove

1. Inventory installed plugins and loose native files. The owner selects needed
   capabilities, checks source/license/version and approves the destination.
2. Use the client's documented install mechanism, or a process-local
   `--plugin-dir` mount for an isolated check. A plugin mount does not install
   arbitrary user instructions. Never alter global settings implicitly.
3. Before updating, record the installed version and preserve owned local edits.
   Update only the selected source; verify native discovery and actual behavior
   with its relevant checks. Static discovery alone is not model compliance.
4. Roll back using the saved version/revision and owned-file backup; verify again.
   If a source is unpublished, use a separately checked-out revision with a
   process-local mount rather than claiming a registry rollback exists.
5. Remove installed or loose copies only with explicit owner approval.
   **Removing a plugin's catalog listing does not uninstall existing plugins.**

## Evidence limits

The ten technical custom-eval scenarios use ordinary declared inputs, including
14 minimal synthetic skill/instruction files. They are test data, not a shipped
solution library. Offline checks do not prove personal-composition compliance
or automatic instruction injection. Role-wide live loading is not established.
Full RPI evaluation remains fail-closed `blocked_approval`.

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

An optional example is **[agentic-persona](https://github.com/hoffe86/agentic-tools)**.
That repository owns its packaging, activation and verification; it is not a
core dependency. Its native instructions require separate opt-in. No particular
user name, local path or personal package is required.

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
   **Marketplace removal does not uninstall existing plugins.**

## Evidence limits

The ten technical custom-eval scenarios use ordinary declared inputs, including
14 minimal synthetic skill/instruction files. They are test data, not a shipped
solution library. Offline checks do not prove personal-composition compliance
or automatic instruction injection. Role-wide live loading is not established.
Full RPI evaluation remains fail-closed `blocked_approval`.

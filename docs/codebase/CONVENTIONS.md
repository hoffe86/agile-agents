# Authoring and configuration conventions

## Put the rule with its owner

Change a **role** when responsibility changes and a **skill** when a reusable
method changes. If a rule names a solution's framework, tracker fields, cloud
provider or actual build command, it usually belongs in that solution, not in
core. User preferences may require stricter consent; they cannot waive a
solution constraint or a human approval. See [customization ownership](../customization-ownership.md).

## Names, layout and discovery

Core agents are flat `name.agent.md` definitions; skills are flat
`name/SKILL.md` entry points with references and scripts alongside the entry
point when needed. Agent and skill names are distinct. The manifest declares
what the host can discover; a file in an arbitrary directory is not a runtime
registration. Skills keep reusable methods at the entry point and load detailed
references on demand rather than importing all guidance into every conversation.

Skill frontmatter uses a matching `name`, a folded `description` and a nonempty
`metadata.applies_to`. Scope is advisory. `metadata.model_tier` on an agent
expresses capability intent; it does not select a runtime model. The profile
may record preferences, but native configuration and host policy determine
what actually runs.

## Changes, failures and evidence

Prompt edits can change runtime behavior. Frontmatter checks, reference audits,
token budgets and the plugin version check catch different kinds of drift;
none judges the quality of a design. `AGENTS.md` is generated from the profile
and definitions, not hand-edited. Documentation for readers belongs under
`docs/`; the site's generated projection is not a source.

An author names what changed, the test or check that demonstrates it, and why
any existing test had to change. A missing command, malformed hand-off or
unavailable measurement stays visible as such. Use the [hand-off contracts](../flow/handoffs.md)
for result fields and the event schema for telemetry. The log must not contain
secrets or full file contents. A hand-off is different: when a design
deliverable belongs on an external documentation platform that the architect
cannot write to, it supplies the **full publishable content and its intended
destination**, rather than a log excerpt or an invented link.

**Evidence:** [contributor rules](../../.github/copilot-instructions.md),
[generated guidance mapping](../AGENTS-MD-MAPPING.md),
[model-tier decision](../adr/0007-model-tier-convention.md),
[event contract](../../plugins/agile-agents-core/skills/run-event-log/references/event-schema.json).

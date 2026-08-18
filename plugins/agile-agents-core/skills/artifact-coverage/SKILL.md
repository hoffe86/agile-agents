---
name: artifact-coverage
description: >-
  Work out which capabilities the agent harness needs for a given stack, which
  installed skills cover them, and where the gaps are — then judge whether a candidate
  artifact is worth adopting and which plugin it belongs in. USE FOR "what capability
  are we missing", "which plugins does this stack need", "is there already a skill for
  X", "where should this new skill live", auditing coverage after a stack change, or
  assessing an artifact found upstream. Demand-first — derive what the phases need
  before looking at what any source offers.
applies_to: all
---

# Artifact coverage

The method behind a coverage question. Used by `capability-scout`; also useful standalone when someone
asks "do we have anything for X?"

**Derive demand before looking at supply.** The question is *"what does each phase need, and do we
have it?"* — not *"what is available, and is any of it nice?"* The first finds gaps by
construction; the second finds them by luck, and only after something has already gone wrong.

## 1. Establish the demand

Read the stack from `solution-profile.yaml` — `tech_stack.primary_languages`,
`infrastructure.iac_tool`, `infrastructure.cloud`, `backlog.platform`, `testing.e2e.framework`.
That set, crossed with the phases the pipeline runs, *is* the demand:

| Phase | What it needs a skill for |
|---|---|
| Research | design authoring, decision records, platform grounding |
| Plan | work-item content standards, tracker mechanics |
| Implement | language implementation, IaC authoring, pipeline authoring |
| Test | unit-test authoring per language, IaC tests, e2e where there is a UI |
| Gates | lint / autofix, startup discovery, deploy preflight |
| Review | the general lens plus per-ecosystem depth (design patterns, provider idioms) |
| Done | PR description, release notes, commit conventions |

## 2. Establish the supply

The skills actually present, and — importantly — whether anything **routes** to them. A skill
nothing names is reachable only by description match, which is the weakest form of selection.
`applies_to` does **not** filter anything (see `.github/copilot-instructions.md` § Skill format),
so presence in a plugin is what decides availability, not the declared scope.

## 3. Classify every cell honestly

`covered` / `gap` / `n/a` / `built-in` — and **never leave `n/a` unexplained**. An unexplained
empty cell gets re-opened by the next reader, wasting the run. "Nothing to start here" and "I
could not work out how to start it" are different claims; so are "this ecosystem has no linter
skill because its formatter is built in" and "we are missing a linter skill".

A worked example, with this marketplace's own current coverage and its declined list:
[`references/coverage-matrix.md`](references/coverage-matrix.md). The trusted upstreams to search
once a gap is named — and why each earns that trust — are in
[`references/sources.yaml`](references/sources.yaml).

## 4. Judge a candidate

In order, stopping at the first that disqualifies:

1. **Does it fill a named gap?** If not, say which capability it *adds* and why the harness needs
   one. Supply-driven adoption is how a skill library accretes weight nothing routes to.
2. **Is it in technology scope?** Azure / .NET / Python / Bicep / Terraform, or genuinely neutral.
3. **Does something already cover it?** Overlap is the commonest reason to decline — name the
   existing skill and what the candidate adds beyond it.
4. **Does it conflict with the harness's design?** Anything re-implementing review fan-out, task
   planning or gating competes with the agents rather than serving them. Size is a signal: an
   artifact that dwarfs the agent it would serve is a methodology, not a skill.
5. **Does it drag in a dependency?** A CLI, a container, a hosted service — a new prerequisite for
   everyone who installs that plugin.
6. **Can it be loaded at all?** Plugins carry `agents/` and `skills/` only.
   Instructions and prompts have no manifest key, so they would ship inert; their content can only
   be re-authored, which makes it hand-written rather than vendored.

## 5. Place it

| The artifact assumes… | Plugin |
|---|---|
| nothing beyond general engineering | `agile-agents-core` |
| .NET / C# | `agile-agents-dotnet` |
| Python | `agile-agents-python` |
| Bicep | `agile-agents-bicep` |
| Terraform | `agile-agents-terraform` |
| Azure, but no single IaC tool | `agile-agents-azure` |
| ADO Boards / GitHub Issues | `agile-agents-ado` / `agile-agents-github` |

**Judge by what the content assumes, not by what its description claims.** An artifact described
as "Azure deployment validation" whose body is entirely Bicep syntax belongs with Bicep — the
asymmetry decides it: Bicep implies Azure, so no Bicep user is mis-served, while Azure does not
imply Bicep, so a Terraform-on-Azure user would be. Count the ecosystem-specific terms first.

## 6. A gap with no candidate is still a finding

Say the gap exists and that nothing fills it. That is what tells a human to write one — which is
how the startup-discovery skills came to exist. A report that recommends nothing is a useful
result; padding it with marginal finds is not.

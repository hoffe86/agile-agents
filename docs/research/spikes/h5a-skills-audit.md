# H5A — AgentSkills.io Conformance Audit (Hand-Written Skills)

**Date:** Audit performed on the current `skills/` tree.
**Scope:** Hand-written SKILL.md frontmatter only. Vendored skills (per `VENDORED.md`)
and `*.agent.md` files were excluded.

## Spec sources

- Anthropic AgentSkills spec — `https://github.com/anthropics/skills/blob/main/README.md`
  ("just a folder with a `SKILL.md` file containing YAML frontmatter and instructions";
  required keys: `name`, `description`).
- GitHub awesome-copilot CONTRIBUTING — `https://github.com/github/awesome-copilot/blob/main/CONTRIBUTING.md`
  (specific, action-oriented descriptions; consistent kebab-case naming).

## Conformance criteria applied

| Criterion | Required? | Notes |
|---|---|---|
| `name` present, kebab-case, matches dirname | yes | hard fail |
| `description` present, single paragraph, action-oriented | yes | hard fail |
| Trigger phrases (`USE FOR …`, `Triggered by …`) | recommended for user-invoked skills | system/orchestrator-loaded skills are exempt and use `Loaded by <agent>` instead |
| `version`, `inputs`, `outputs` | optional | none of our skills currently use these and the spec does not require them |

## Skills audited

21 hand-written skills (16 pre-existing + 5 added in Wave 1: `code-localisation`,
`run-event-log`, `test-bar-gate`, `e2e-testing`, `cost-budget`).

| # | Skill | Type | name OK | description OK | Trigger phrases | Verdict |
|---|---|---|---|---|---|---|
| 1 | architecture-decision-records | user-invoked | ✓ | ✓ | USE FOR + Triggered by | conformant |
| 2 | architecture-design | user-invoked | ✓ | ✓ | USE FOR + Triggered by | conformant |
| 3 | bicep-implementation | user-invoked | ✓ | ✓ | USE FOR + Triggered by | conformant |
| 4 | cicd-pipeline-implementation | user-invoked | ✓ | ✓ | USE FOR + Triggered by | conformant |
| 5 | code-localisation | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |
| 6 | code-review-checklist | user-invoked | ✓ | ✓ | USE FOR | conformant |
| 7 | cost-budget | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |
| 8 | csharp-implementation | user-invoked | ✓ | ✓ | USE FOR + Also triggered by | conformant |
| 9 | csharp-testing | user-invoked | ✓ | ✓ | USE FOR | conformant |
| 10 | e2e-testing | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |
| 11 | helm-kustomize-implementation | user-invoked | ✓ | ✓ | USE FOR + Triggered by | conformant |
| 12 | iac-best-practices | user-invoked | ✓ | ✓ | USE FOR | conformant |
| 13 | pr-description | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |
| 14 | python-implementation | user-invoked | ✓ | ✓ | USE FOR | conformant |
| 15 | python-testing | user-invoked | ✓ | ✓ | USE FOR | conformant |
| 16 | read-repo-context | orchestrator-loaded | ✓ | ✓ | Use as the first action … | conformant |
| 17 | release-notes | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |
| 18 | reviewer-read-only-rules | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |
| 19 | run-event-log | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |
| 20 | terraform-azure-implementation | user-invoked | ✓ | ✓ | USE FOR + Triggered by | conformant |
| 21 | test-bar-gate | orchestrator-loaded | ✓ | ✓ | Loaded by | conformant |

## Summary

- **Total hand-written skills audited:** 21
- **Already conformant:** 21
- **Edited (frontmatter):** 0
- **Need human review:** 0

## Findings

1. Every hand-written skill has a kebab-case `name` matching its directory and a
   single-paragraph, action-oriented `description`. No frontmatter edits were
   required.
2. The 12 user-invokable skills all surface explicit trigger phrasing
   (`USE FOR …` and/or `Triggered by …` quoted phrases), which is what
   skill-routing matches against.
3. The 9 orchestrator-loaded skills (`pr-description`, `release-notes`,
   `reviewer-read-only-rules`, `read-repo-context`, `run-event-log`,
   `test-bar-gate`, `code-localisation`, `cost-budget`, `e2e-testing`)
   intentionally use `Loaded by <agent>` framing instead of user trigger
   phrases. This is correct: those skills are pulled in by `dev-lead` /
   author / reviewer agents, not by user prompts. Adding fake user triggers
   would cause spurious skill matches.
4. False alarm during audit: the initial bulk dump of frontmatter via
   PowerShell appeared to show a stray `,\n,` in the `csharp-testing`
   description. Direct inspection of the file confirmed it was a terminal
   line-wrapping artifact, not a real defect. The file is clean.
5. None of the skills currently declare optional keys (`version`, `inputs`,
   `outputs`). The AgentSkills spec does not require them, so no action
   taken — flag as a future improvement only if/when these become load-bearing
   (e.g., for skill versioning during distribution).

## Recommendations (out-of-scope for this audit, defer)

- Consider adding a `version: <semver>` key to all hand-written skills once a
  release/distribution mechanism exists. Helps downstream repos detect drift
  when re-syncing.
- Consider a lightweight pre-commit check that asserts every `SKILL.md` has
  `name:` matching its directory and a non-empty `description:` ≥ 60 chars.

# Vendored skills

## Skill → Upstream

| Skill | Plugin | Upstream |
|---|---|---|
| acquire-codebase-knowledge | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/acquire-codebase-knowledge |

Use only for explicit onboarding. Preserve upstream bodies, resources and
licensing; do not edit in place. The only sanctioned local change is the
standalone `metadata.applies_to` annotation (and its bare wrapper when needed).
Preserve inherited metadata, including `version` and `enhancements`.

`scripts/check-vendored-drift.ps1` normalizes only CRLF/LF and that annotation.
Malformed/duplicate YAML, upstream scope collisions, aliases, merged or complex
annotation placements fail closed. Review drift and obtain approval before sync;
contribute improvements upstream rather than growing local exceptions.

Other shipped skills are locally maintained.

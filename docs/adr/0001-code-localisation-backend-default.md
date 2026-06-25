# ADR 0001 — Code-localisation backend default (`auto` over 3 backends, tree-sitter as fallback)

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H1)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H1)

## Context

Coding, architect, and reviewer agents need to find the small set of files
relevant to a task without grepping the whole repo blindly. Industry evidence
(Sourcegraph file-recall jumping from 0.127 → 0.277 with a localisation step;
the consistent appearance of Agentless-style localisation across all top
SWE-bench performers — see research §13.4) makes this the single
highest-leverage upgrade we can ship.

There are three credible backend families in the field today:

1. **tree-sitter repo-map** — Aider's approach. Pure local, parses the AST,
   ranks files/symbols by structural relevance. Zero infra, zero secrets,
   works offline.
2. **embedding + LLM rerank** — Agentless / RepoCoder (arXiv:2303.12570). Higher
   recall, but requires an embedding endpoint and (usually) a vector store.
3. **MCP semantic-code server** — Sourcegraph-style: delegates to a running
   semantic-code MCP endpoint. Best on monorepos, but adds an external
   dependency.

We must pick a *default* the agents fall back to when the project hasn't
explicitly chosen one — this default lands in every customer repo we generate
from `template/`.

## Decision

We expose `code_localisation.backend` in `solution-profile.yaml`
with the values `auto | tree-sitter | embedding-rerank | mcp` and **default to
`auto`**. The `code-localisation` skill resolves `auto` in this order:

1. If `mcp_server` is set → use `mcp`.
2. Else if an Azure OpenAI embedding endpoint is reachable → use
   `embedding-rerank`.
3. Else → use **`tree-sitter`** (the universal fallback).

Tree-sitter is the *guaranteed* fallback because it has no external
dependencies — it works in air-gapped customer environments, behind proxies,
on the train, and on a fresh checkout with no secrets configured. The 5000-file
ceiling (`code_localisation.repo_map_max_files`) protects against runaway
parses on large monorepos.

The dev-lead (`agents/dev-lead.agent.md`) does not
call `code-localisation` itself; it only validates that the profile field is
populated (or that the `tree-sitter` default is acceptable) and propagates
that fact to workers in the hand-off context.

## Consequences

**Positive**
- Out-of-the-box experience works in every repo, including air-gapped ones.
- Customers with embedding infra get the higher-recall path without code
  changes — only a profile flip.
- Backend choice is a single field, not a code change in agents.

**Negative**
- Tree-sitter recall is lower than embedding+rerank on large repos; some
  customers will see less-relevant file selection until they configure a
  better backend.
- Three backends → three code paths to maintain in the `code-localisation`
  skill.

## Alternatives considered

- **Default to `embedding-rerank`.** Rejected: would silently degrade in
  air-gapped projects (Bundeswehr SÜ3, sovereign cloud) and require Azure
  OpenAI credentials at agent startup.
- **Default to `mcp`.** Rejected: nobody has a Sourcegraph-style MCP endpoint
  by default; would force every customer to stand up infra before the suite
  works at all.
- **Single backend, no `auto`.** Rejected: forces a per-project choice up front
  even when the project has no opinion yet (typical for PoCs).

## References

- `solution-profile.yaml` lines 145–157 (`code_localisation` block)
- `agents/dev-lead.agent.md` (worker hand-off
  context payload — mentions `code-localisation` availability)
- `docs/research/autonomous-coding-agents-2026.md` §13.4 (Agentless localisation),
  §6 row H1
- Aider repo-map: <https://aider.chat/docs/repomap.html>
- RepoCoder: Zhang et al., arXiv:2303.12570

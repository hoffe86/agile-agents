---
name: code-localisation
description: Locate the small set of code files relevant to a task in a large repository. Three backends (tree-sitter repo-map, embedding+LLM rerank, MCP semantic-code server) selected via solution-profile.yaml `code_localisation.backend`. Loaded by `coding`, `architect`, and review agents on Stage 2/3+ when the task touches code (skip for IaC-only or doc-only changes).
---

# Code Localisation

Pick the **small set of files** an agent actually needs to read for a code-touching task, instead of grepping blindly or reading the whole repo.

Plain-file reads achieve only **0.127 file-recall** on Sourcegraph CodeScaleBench, vs **0.277** for semantic search — more than a 2× recall gap. Localising first is one of the highest-leverage moves an autonomous coding agent can make on a non-trivial repo.

References:
- Agentless (arXiv:2407.01489) — embedding + LLM rerank pattern that took SOTA on SWE-bench Lite at the time.
- Aider repo-map — https://aider.chat/docs/repomap.html — tree-sitter outline + graph proximity.

## When to load this skill

Load when **all** of:
- The task touches source code (not pure IaC, not pure docs).
- The repo has more than ~30 source files (below that, plain glob+grep is faster and cheaper).
- The task description does not pin a specific file path the agent already knows is correct.

**Skip when:**
- Single-file edit with an explicit path (e.g. "add null check in `src/payments/processor.cs:142`").
- IaC-only change (Bicep / Terraform / Helm / Kustomize / pipeline file) — those are usually layout-driven, not symbol-driven.
- Doc-only change.
- Repo is small (~30 files or fewer).

## Backends

Selection is read from `solution-profile.yaml: code_localisation.backend`. Default if missing or empty: `tree-sitter`.

| Backend            | Profile value         | When                                                                  |
|--------------------|-----------------------|-----------------------------------------------------------------------|
| Tree-sitter repo-map | `tree-sitter`       | Default. Zero external deps, multi-language, good for small/medium repos.|
| Embedding + LLM rerank | `embedding`       | Azure OpenAI / OpenAI endpoint available; medium-large repos; semantic queries. |
| MCP semantic-code server | `mcp`           | Project provides a Sourcegraph-style or `mcp-semantic-code` MCP endpoint; monorepos. |

Detailed catalogue, pseudo-code, and decision matrix: see `references/localisation-backends.md`.

## How to invoke

1. Read `solution-profile.yaml: code_localisation.backend` and `code_localisation.max_files` (default cap **15**, floor **5**).
2. Dispatch:
   - **`tree-sitter`** → run `scripts/repo_map.py --root <repo> --query "<task description>" --max-files <cap>`.
   - **`embedding`** → call the configured embedding endpoint (`code_localisation.embedding_endpoint`, `code_localisation.embedding_model`); top-K cosine similarity then a single LLM rerank pass with full file content of the top candidates.
   - **`mcp`** → call the MCP server named in `code_localisation.mcp_server` with the task description as the query.
3. Validate the response shape (see Output contract).
4. Pass the result forward in your hand-off so reviewers and downstream workers don't re-localise.

## Output contract

A ranked JSON array, 5–15 entries (capped by `code_localisation.max_files`):

```json
[
  { "path": "src/payments/processor.cs", "score": 0.91, "why": "defines ProcessPayment, top symbol overlap with query" },
  { "path": "src/payments/refund.cs",    "score": 0.74, "why": "co-changed with processor in last 5 commits" }
]
```

- `path` — repo-relative POSIX path.
- `score` — float in `[0,1]`, higher = more relevant. Backend-defined; do not normalise across backends.
- `why` — one short sentence explaining the rank. Required (auditability).

If the result is empty, surface that to the orchestrator/user instead of silently proceeding — the agent should fall back to manual exploration with a logged note.

## Failure modes &amp; fallback

Cascade, in order:

1. **Configured backend unreachable / errors** → fall back to `tree-sitter` (the default). Log the fallback in the hand-off (one line: `code-localisation: <chosen> backend failed (<reason>), used tree-sitter`).
2. **Tree-sitter unavailable** (e.g. `tree_sitter_languages` not installed, or no parser for the dominant language in the repo) → `repo_map.py` falls back to a path-based heuristic (term overlap on path components + symbol-name guesses from file names + mtime tiebreak). Still emits the same JSON shape; the `why` field calls out the degraded mode.
3. **Path heuristic returns nothing useful** → fall back to `glob` + `grep` for query terms across `**/*.{cs,py,ts,js,go,java,rs,kt,rb,php}` (or whatever the profile says are the source languages). Cap at the same `max_files`.

The agent never fails the turn just because localisation failed; it degrades to plain exploration with a logged trade-off.

## Honoured profile fields

- `code_localisation.backend` — `tree-sitter` | `embedding` | `mcp` (default `tree-sitter`).
- `code_localisation.max_files` — int, default 15.
- `code_localisation.embedding_endpoint`, `code_localisation.embedding_model` — required when backend is `embedding`.
- `code_localisation.mcp_server` — required when backend is `mcp`.
- `tech_stack.languages` — used to bound the fallback glob.

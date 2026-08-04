# Localisation backends — detailed catalogue

Three backends are supported. The agent picks one based on `solution-profile.yaml: code_localisation.backend` and the cheat-sheet at the bottom.

All three return the **same JSON shape** (see `SKILL.md` → Output contract) so downstream agents don't care which backend produced the list.

---

## Backend 1: tree-sitter repo-map (default)

Inspired by Aider's repo-map (https://aider.chat/docs/repomap.html). Zero external service dependency.

### How it works

1. Walk the repo (respecting `.gitignore`).
2. Parse each source file with `tree_sitter_languages` to extract **top-level definitions**: functions, methods, classes, modules, exported constants.
3. Build a lightweight outline: per-file list of `(symbol_name, kind, line)`.
4. Optionally: build a coarse **call/import graph** (who imports whom, who calls whom) — Aider uses graph proximity to the query as a signal.
5. Score each file against the query:
   - **Symbol-name overlap** — how many query terms appear in the file's symbol names (highest weight).
   - **Path-component overlap** — query terms in directory / filename components.
   - **Graph proximity** — neighbours of the highest-scoring files get a bonus (helps surface helper modules).
   - **Recency** — mtime as a tiebreaker.
6. Return the top-K (capped by `max_files`).

### Pseudo-code

```python
files = walk(repo, respect_gitignore=True)
outline = {f: parse_top_level_symbols(f) for f in files}
graph = build_import_graph(outline)

scores = {}
for f in files:
    s = symbol_term_overlap(outline[f], query)        # weight 0.55
    s += path_term_overlap(f, query)                   # weight 0.30
    s += graph_proximity_bonus(f, graph, top_so_far)   # weight 0.10
    s += recency_bonus(f)                              # weight 0.05
    scores[f] = s

return sort_desc(scores)[:max_files]
```

### Pros / cons

- ✅ Zero deps (only `tree_sitter_languages`, optional). No network. No index to maintain.
- ✅ Multi-language out of the box.
- ✅ Deterministic — same query, same repo state → same answer.
- ❌ No semantic similarity (synonyms / paraphrases miss).
- ❌ Slow on huge monorepos (parse cost).
- ❌ Tree-sitter parser quality varies per language.

A reference implementation lives at `scripts/repo_map.py`.

---

## Backend 2: embedding + LLM rerank (Agentless-style)

Pattern from the **Agentless** paper (arXiv:2407.01489) — at publication, this approach took SOTA on SWE-bench Lite by combining embedding retrieval with an LLM reranking pass.

### How it works

1. **Index** (one-time, then incremental):
   - Chunk source files (per function, or fixed-token windows ~500 tokens with ~50 overlap).
   - Embed each chunk with a strong code-aware model — e.g. `text-embedding-3-large`, `text-embedding-3-small`, or an Azure OpenAI deployment thereof.
   - Persist `(file, chunk_id, vector, span)` tuples (FAISS / Azure AI Search / pgvector / SQLite-VSS — implementation detail).
   - Re-embed only changed files on subsequent runs.
2. **Query**:
   - Embed the task description with the same model.
   - Top-K cosine similarity (e.g. K=30 chunks).
   - Group hits by file, sum/max scores.
3. **Rerank** (the high-signal step Agentless adds):
   - Take the top-K-by-file candidates (e.g. top 10 files).
   - Send each file's full content + the task description to an LLM with a one-shot rank prompt: "Of these N files, which are most likely to need editing for this task? Rank with one-sentence justification."
   - Return the LLM's ranking as the final list.
4. Cap by `max_files`.

### Pros / cons

- ✅ Best-evidenced approach for natural-language queries ("the bug where refunds double-process if the user retries").
- ✅ Handles synonyms / paraphrases / cross-language references.
- ✅ Scales: index is `O(files)`, query is `O(K)` similarity + 1 LLM call.
- ❌ Requires an embedding endpoint (Azure OpenAI, OpenAI, or self-hosted).
- ❌ Index must be kept fresh — stale index returns wrong files.
- ❌ Embedding cost on first index of a large monorepo can be material (budget for it).
- ❌ Rerank LLM call adds latency (~5–15s).

### Profile fields needed

- `code_localisation.embedding_endpoint` — URL of the embeddings endpoint.
- `code_localisation.embedding_model` — e.g. `text-embedding-3-large`.
- `code_localisation.embedding_index_path` — where the index lives (default `.code-localisation/index/`).

---

## Backend 3: MCP semantic-code server

Defer to an external **MCP server** that already exposes semantic code search — typically a Sourcegraph deployment, an internal `mcp-semantic-code` server, or a vendor equivalent.

### How it works

1. The project stands up the MCP server (Sourcegraph, GitHub's code search MCP, or a custom one). The agent does not own this infrastructure.
2. Agent calls the MCP server with the task description and `max_files`.
3. Server returns ranked file paths; agent maps them to the canonical output shape.

### Pros / cons

- ✅ Best for **monorepos** (10k+ files) — the external service has a real index and was built for this.
- ✅ Index freshness is the server's problem, not the agent's.
- ✅ One MCP server can be shared across many repos / many agents.
- ❌ Requires hosted infrastructure (and budget, and ops).
- ❌ Network round-trip — slowest of the three on small repos.
- ❌ Coupled to whatever ranking the server uses; less control.

### Profile fields needed

- `code_localisation.mcp_server` — name of the registered MCP server (must already be configured at the Copilot CLI level).

---

## Decision matrix

| Repo profile                                          | Recommended backend |
|-------------------------------------------------------|---------------------|
| Small repo (≤500 files), single stack                 | `tree-sitter`       |
| Small repo, cross-stack (e.g. C# + Python + TS)       | `tree-sitter`       |
| Medium repo (500–5000 files), Azure OpenAI available  | `embedding`         |
| Medium repo, no embedding endpoint                    | `tree-sitter`       |
| Monorepo (5000+ files), Sourcegraph / MCP available   | `mcp`               |
| Monorepo, no MCP infra                                | `embedding` (with budget) |
| Air-gapped / no external services                     | `tree-sitter`       |
| Highly natural-language queries ("the bug where…")    | `embedding` or `mcp`|
| Symbol-pin queries ("rename `parsePayment` everywhere") | `tree-sitter`     |

---

## References

- **Agentless: Demystifying LLM-based Software Engineering Agents** — Xia et al., arXiv:2407.01489. https://arxiv.org/abs/2407.01489 — embedding + rerank pattern.
- **Aider repo-map docs** — https://aider.chat/docs/repomap.html — tree-sitter outline approach.
- **Sourcegraph CodeScaleBench** — file-recall benchmark (0.127 plain reads vs 0.277 semantic search). Cited in `skills/.../stream-d-bench.md` and the autonomous-coding-agents-2026 whitepaper.
- **tree-sitter** — https://tree-sitter.github.io/ — incremental parsing library powering both backend 1 and Aider's repo-map.

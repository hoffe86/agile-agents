# ADR 0007 — Record advisory model tiers in Copilot agent metadata

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** Repository owner

## Context

The harness records a `light`, `mid`, or `heavy` model-tier preference for
each of its 15 agents. These labels express advisory intent, not a model
selection mechanism. The agent definitions now record this intent under
`metadata.model_tier`; no repository resolver consumes it.

GitHub's [custom agent configuration reference](https://docs.github.com/en/copilot/reference/custom-agents-configuration)
documents a string-to-string `metadata` map for annotations. This gives
the convention a supported home without introducing a custom model
resolver. The annotation container is native; the meaning of
`model_tier` remains repository-defined.

This annotation contract is specific to Copilot.
[OpenCode's agent reference](https://opencode.ai/docs/agents/#additional)
documents additional agent options as being passed directly to the
provider as model options, not stored as inert annotations.
[Claude Code's frontmatter reference](https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields)
does not document a general-purpose agent metadata map. A shared
Markdown/YAML shape therefore does not establish equivalent annotation
semantics or a portable agent configuration contract.

The priorities are to use the native annotation mechanism, distinguish
intent from runtime controls, and record the owner's approved tier assignments.
The labels alone establish neither required reasoning capacity nor
measured savings: orchestration can require substantial judgement, and
model suitability depends on the actual task and evaluation evidence.

## Decision

Adopt **`metadata.model_tier`** as the convention for advisory tier intent
in Copilot agent frontmatter, with exactly the values `light`, `mid`, and
`heavy`. For example:

```yaml
metadata:
  model_tier: heavy
```

Native configuration fields such as `model` and `tools` remain at the
top level; they are not annotations and must not move into `metadata`.
Actual model selection is governed by Copilot's runtime-native settings
and documented precedence, including a top-level `model` when configured,
as described in the [Copilot CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference).
The tier does not override those controls.

This decision does **not** introduce a custom resolver or map tiers to
concrete model identifiers. It does not automatically enforce
`ai_copilot.approved_models` in
[`.github/solution-profile.yaml`](../../.github/solution-profile.yaml),
authorize a model, or enforce a cost budget.

Record the approved assignments in
[`plugins/agile-agents-core/agents/`](../../plugins/agile-agents-core/agents/):

| Tier | Agents |
| --- | --- |
| `light` | None currently; remains a supported value |
| `mid` | `backlog-manager`, `bootstrapper`, `coding`, `infrastructure` |
| `heavy` | `architect`, `architecture-reviewer`, `capability-scout`, `code-reviewer`, `data-reviewer`, `data-scientist`, `dev-lead`, `infrastructure-reviewer`, `review-lead`, `security-reviewer`, `test-reviewer` |

The owner explicitly assigns `dev-lead` to `heavy`: planning/decomposition,
acceptance coverage, risk sequencing, and gate judgement require deep reasoning,
not merely mechanical orchestration. The other 14 assignments are unchanged,
giving 0 light, 4 mid, and 11 heavy agents. These are advisory preferences,
not guarantees that any particular model will meet their needs.

All 15 agent definitions conform to this convention. OpenCode or Claude
adapters, skill metadata migration, and further changes to tier assignments are
outside this decision.

## Consequences

**Positive**
- Custom intent has a documented annotation location, separate from
  executable configuration such as model selection and tool grants.
- The 15-agent tier inventory captures `dev-lead`'s planning responsibility
  without coupling assignments to model identifiers or adding a resolver.
- Runtime-native configuration remains authoritative; advisory labels
  cannot be mistaken for implemented approved-model enforcement.

**Negative**
- A tier label cannot establish which model actually ran. Operators must
  inspect runtime configuration and available execution evidence.
- Tier preferences may diverge from runtime choices. Any claim about
  quality, latency, or savings requires measurement rather than inference
  from the labels.
- The metadata convention is Copilot-specific, not a cross-runtime
  abstraction. Any future adaptation needs a separate decision based on
  the target runtime's documented contract.
- The metadata move does not itself change runtime model selection and
  remains reversible.

## Alternatives considered

- **Keep top-level `model_tier`.** Rejected: it is not a documented
  Copilot model selector or annotation field; the supported metadata
  container expresses its advisory purpose more clearly.
- **Remove tier intent entirely.** Rejected: the owner chose to retain
  advisory preferences while clarifying their non-executable meaning.
- **Replace tiers with concrete top-level `model` values everywhere.**
  Rejected as a replacement for advisory intent: this would configure
  model selection rather than merely record a preference. Native `model`
  configuration remains available where deliberately needed.
- **Build a custom tier-to-model resolver with approved-model enforcement.**
  Rejected: this adds execution policy and maintenance beyond the chosen
  annotation convention. No such resolver is implemented or approved by
  this decision.
- **Define a common metadata abstraction or add runtime adapters.**
  Rejected: the documented agent contracts differ, and portability work
  is outside this change.

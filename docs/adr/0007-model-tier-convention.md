# ADR 0007 — `model_tier: light | mid | heavy` semantic frontmatter (with optional `model:` override)

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (companion to H4)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H4); Stream E "Cost Economics", §21 (Shopify mid-tier fine-tune)
- **Note (2026-08):** ADR 0009 merged `testing` into `coding`, so the `mid` row below is now `coding`, `infrastructure`, `backlog-manager`. The tiering convention itself is unchanged.

## Context

Different agent roles in the suite have wildly different reasoning
demands. The dev-lead orchestrates — high call volume, low reasoning load.
Authors (coding, testing, infrastructure) do middling reasoning over
focused scope. The architect and reviewers do the heaviest reasoning over
the broadest context.

Hard-coding model IDs in agent frontmatter would mean:

- Every model upgrade (e.g., `gpt-5.4` → `gpt-5.5`) is a sweeping edit
  across 11 agent files.
- Customer-specific approved-model lists (`ai_copilot.approved_models`
  in `solution-profile.yaml`) require forking the agents.
- Cost-tier intent ("this role should be cheap, not premium") is implicit
  rather than declared — invisible to the cost-budget skill.

Stream E's cost analysis (15× chat-token cost in agentic flows;
Shopify's mid-tier fine-tune yielding 2.2× faster and 68% cheaper) makes
clear that *tiering by role* is the dominant cost lever — bigger than
prompt tuning, bigger than context compression.

## Decision

Each agent declares a **semantic tier** in YAML frontmatter:

```yaml
model_tier: light | mid | heavy
model: ""   # optional explicit override — usually empty
```

Tier resolution to a concrete model is a property of the *runtime* (not
the agent file): the harness or runner reads `model_tier`, looks up the
matching entry in `solution-profile.yaml: ai_copilot.approved_models`,
and binds. An explicit `model:` field overrides the tier mapping for
that single agent — used sparingly for known-good pairings.

**Tier assignments** for the suite:

| Tier | Agents | Why |
| --- | --- | --- |
| `light` | `dev-lead` | Orchestrator. High call volume, low per-call reasoning — the work is dispatch and parsing, the heavy thinking is delegated. |
| `mid` | `coding`, `testing`, `infrastructure` | Authoring. Focused scope (one task at a time), bounded context, deterministic gates downstream catch most quality regressions cheaply. |
| `heavy` | `architect`, all 5 review agents (`code-review`, `architecture-review`, `infra-review`, `testing-review`, `security-review`) | Broad context, irreversible decisions, judgement calls. The most expensive errors live here — pay for the reasoning. |

### Why the dev-lead is `light`, not `mid`

The dev-lead's job is to read the profile, parse sentinel blocks, dispatch
sub-agents, and emit JSONL events. None of this is reasoning-heavy. The
reasoning lives in the workers it dispatches. A `light` orchestrator
keeps the per-stage transition cost near-zero so the cost envelope (ADR
0004) is dominated by the work, not the supervision.

### Why authors are `mid`, not `heavy`

Authors operate within a confined task scope (provided by the dev-lead)
and their output flows through the test-bar gate (ADR 0003) and a heavy
reviewer. The combination of bounded scope + downstream review means a
heavy author would mostly pay for capacity it doesn't use.

### Why architect + reviewers are `heavy`

These agents make decisions that propagate forward (architect) or
constitute the final word on quality (reviewers). The cost of a missed
issue or a wrong design decision dwarfs the per-call price difference.

## Consequences

**Positive**
- Model upgrades touch one mapping, not 11 agent files.
- Customer per-tenant model approvals (sovereign cloud, regulated
  customers) are honoured automatically via `approved_models`.
- The cost-budget skill (ADR 0004) can reason about tier mix per run —
  tier intent is now declared, not inferred.
- Future Shopify-style fine-tune of the `mid` tier (research §E6) lands
  in one place.

**Negative**
- One layer of indirection between agent and concrete model. A
  developer reading an agent file no longer sees "this runs on X"
  directly — they need the runtime mapping.
- Misalignment risk: if a customer's `approved_models` list is missing a
  tier, the runner must fail loudly (not silently downgrade).

## Alternatives considered

- **Hard-code `model:` in every agent.** Rejected: O(N) edits per
  upgrade; breaks tenant approved-model isolation.
- **Tier mapping inside each agent's frontmatter.** Rejected: mapping
  duplicated across 11 files; same drift problem as hard-coded model
  IDs.
- **Single global model for the whole suite.** Rejected: discards the
  cost lever entirely; either over-pays for orchestration or
  under-powers reviewers.
- **More tiers (e.g., `xlight | light | mid | heavy | xheavy`).**
  Rejected: three tiers map cleanly onto observable role behaviour;
  finer granularity invites bikeshedding without changing outcomes.

## References

- `agents/dev-lead.agent.md` line 27
  (`model_tier: light` with the orchestrator-vs-specialist rationale
  inline)
- `solution-profile.yaml` lines 134–143
  (`ai_copilot.approved_models`, `responsible_ai_tier`)
- `docs/research/autonomous-coding-agents-2026.md` §6 row H4; Stream E
  "Cost Economics", §21 (Shopify mid-tier fine-tune, 2.2× faster + 68%
  cheaper)

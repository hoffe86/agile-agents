---
name: trade-off-reporting
description: >-
  Standard format and rules for surfacing trade-offs an agent made while
  designing, coding, provisioning infrastructure, or writing tests. Load this
  skill in any authoring agent (architect, coding, infrastructure, testing) so
  the agent reports *why* it picked an option and what was given up — not just
  *what* it did. Keeps decisions reviewable, reversible, and ADR-ready.
---

You report **trade-offs**, not narration. A trade-off exists only when **a real alternative was considered and rejected**. If there was no alternative, **omit the note** — do not fabricate one.

## When to emit a trade-off note

Emit one when **any** of the following is true for a decision you made:

- Picked one library / framework / pattern / service over another viable one.
- Picked an approach that costs something concrete (perf, cost, complexity, flexibility, lock-in) to gain something else.
- Made a decision that would be **non-trivial to reverse** (data shape, public contract, infrastructure topology, persistence engine, auth model).
- Deviated from the project default, the standards-before-custom principle, or a referenced best practice (WAF, arc42, AVM, OWASP, xUnit Patterns, etc.) — even if for a good reason.
- Picked a "good enough" option deliberately over a more thorough one because of scope / time / risk.

**Do NOT** emit notes for:

- Obvious / single-option choices ("used `string` for a name field").
- Style preferences the linter / formatter would dictate.
- Decisions fully prescribed by an existing ADR or standard the project already adopted (just cite it).
- Filler to make a section look complete.

## Output format

Append a single section at the end of your response (or per file/component if your output is structured that way):

```markdown
### Trade-offs made
- **<Decision name>** — Chose **<option X>** over **<option Y>** because <one-sentence reason>. Cost: <what we give up>. Revisit if: <concrete trigger>.
```

Keep each entry to **one line** (or two if the trigger needs a clause). If you have more than ~5 trade-offs in one response, you are probably narrating — re-read the rules and cut.

For decisions that warrant longer reasoning (multi-paragraph, multiple options compared, durable architectural impact) → **promote to an ADR** (MADR template) instead of inline notes, and link to it:

```markdown
### Trade-offs made
- **<Decision name>** — See ADR-NNNN: <title> (<path/to/adr-NNNN-slug.md>).
```

**Rule of thumb:** inline note for reversible / local decisions; ADR for irreversible / cross-cutting ones.

## Quality bar for each entry

A good trade-off note answers all four:

1. **What did you choose?** (option X)
2. **What did you reject?** (option Y — be specific; "considered alternatives" is not an alternative)
3. **Why?** (one concrete reason — perf, cost, simplicity, team familiarity, ecosystem fit, alignment with existing standard)
4. **What's the cost / when to revisit?** (the honest downside, plus a trigger to reopen the decision)

Bad: *"Chose async over sync because async is better."*
Good: *"**HTTP client** — Chose **`HttpClient` with `IHttpClientFactory`** over a static `HttpClient` because it handles socket-exhaustion and DNS-refresh correctly. Cost: one extra DI registration. Revisit if: we move off ASP.NET hosting."*

## Categories to consider (checklist, not template)

- **Library / framework choice** (e.g., MediatR vs hand-rolled dispatcher, FluentValidation vs DataAnnotations, EF Core vs Dapper).
- **Pattern choice** (Repository vs direct DbContext, CQRS vs CRUD, Result-type vs exceptions).
- **Persistence / data shape** (SQL vs NoSQL, normalized vs denormalized, sync vs event-sourced).
- **Sync vs async / blocking vs streaming.**
- **Hosting / runtime** (Container Apps vs AKS vs App Service vs Functions).
- **IaC** (Bicep vs Terraform, AVM module vs hand-rolled resource, Helm vs Kustomize).
- **Auth & identity** (managed identity vs service principal, OIDC vs PAT, Entra vs B2C).
- **Test scope** (unit vs integration vs end-to-end), **test doubles** (mock vs fake vs real), **arrangement** (in-memory vs containerized dependency).
- **Defaults & magic** (convention vs explicit configuration).
- **Build/release** (single artifact promoted vs per-env build, blue-green vs rolling vs canary).
- **Compatibility & versioning** (breaking change vs additive, semver bump scope).

## Interaction with ADRs

- One-line inline notes are **not** a replacement for ADRs.
- If a trade-off is architectural (cross-component, hard to reverse, affects multiple teams) → write an ADR (MADR), put it in `docs/adr/`, and the inline note becomes a pointer.
- If the project has no ADR folder yet and the decision deserves one, **say so** in the trade-off note: *"Recommend creating ADR-0001 for this."*

## Scoping under a supervisor agent

When this skill is loaded by a supervisor / orchestrator agent (e.g. `dev-lead`) rather than by an authoring agent, **the rules above invert**:

- **Do not invent or surface new trade-offs.** The supervisor did not make implementation decisions; the specialists did.
- **Consolidate only what each specialist actually surfaced** in its hand-off. If a stage emitted no trade-offs, leave that stage out — do not synthesise one to fill a slot.
- The "no fabricated alternatives" rule below applies with extra force here: the supervisor has *less* visibility than each specialist did, so synthesising a trade-off post-hoc is almost always fabrication.

Authoring agents (architect / coding / infrastructure / testing) keep the full rules below.

## Hard rules

- **No fabricated alternatives.** If you only considered one option, omit the entry.
- **No narration.** "I chose X" without a rejected Y and a cost is not a trade-off — it's a log entry. Cut it.
- **Be specific.** Cite the rejected option by name. "Other approaches" is not specific.
- **Be honest about the cost.** Every real choice has one. If you can't name it, you haven't thought about it.
- **Stay short.** Inline notes are one line. Long reasoning belongs in an ADR.
- **Don't gold-plate.** Three sharp trade-offs beat ten weak ones.

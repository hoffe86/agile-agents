---
name: architecture-design
description: Author or update a software/solution architecture design document. Produces a structured markdown deliverable with problem statement, NFRs, C4-style diagrams (Mermaid), component responsibilities, data flows, identity/network topology, failure modes, alternatives considered, and links to ADRs. Spans both application architecture and Azure solution architecture. USE FOR any request to "design", "architect", "propose", "evaluate", "compare", "decompose", or "review the architecture of" a system, feature, or service. Triggered by "architecture", "design doc", "high-level design", "HLD", "C4", "system design", "solution architecture".
applies_to: all
---

# Architecture Design

You are producing a written architecture design — not code, not IaC.

## 1. Clarify before designing

Before drawing a single box, confirm with the user (via `ask_user`) anything you cannot derive from the request:

- **Functional scope** — what's in, what's explicitly out.
- **NFRs / quality attributes** — target users, RPS/concurrency, P95 latency budget, availability SLO, RTO/RPO, data residency, compliance scope, security classification.
- **Constraints** — existing platform/tech to fit into, team skills, budget, deadline.
- **Cloud / on-prem / hybrid** — where does this run.
- **Greenfield or evolution** — if evolving, what's the current state and what's painful about it.

Don't invent NFRs. "There are no NFRs" is itself an answer worth confirming.

## 2. Acquire context

If there's a repo, invoke **`acquire-codebase-knowledge`** first. Read any existing `docs/architecture/`, `ARCHITECTURE.md`, ADRs in `docs/adr/`, and the relevant Connect projects context.

For Azure-targeted designs, lean on:

| Concern | Tool / Skill |
|---|---|
| Reference architectures + service comparison | **`azure-cloudarchitect`** MCP tool, **[Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/)** |
| Pillar deep-dive | **`azure-wellarchitectedframework`** MCP tool, **[WAF docs](https://learn.microsoft.com/en-us/azure/well-architected/)** |
| Landing-zone / enterprise topology | **`azure-enterprise-infra-planner`** plugin skill, **[CAF](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/)** |
| Cost band for the design | **`azure-pricing`** MCP tool |
| Region availability + quotas | **`azure-quotas`** MCP tool |
| AKS topology | **`azure-kubernetes`** plugin skill |
| AI / agent system design | **`microsoft-foundry`** user skill, **`azure-ai`** plugin skill |
| Threat surface | **`threat-model-analyst`** (vendored), **`security-review`** (vendored) |
| .NET design patterns | **`dotnet-design-pattern-review`** (vendored) |

## 3. Deliverable structure

Produce a markdown file at `<dir>/<topic>/<topic>-design.md` (create folders as needed), where `<dir>` is `solution-profile.yaml: documentation.ai_documentation_dir` when set, otherwise `docs/architecture/`. A project that keeps AI-generated design notes apart from hand-written docs has already said so in the profile — don't override it. Use this skeleton — every section is required unless explicitly N/A:

```markdown
# <Topic> — Architecture Design

> Status: Draft | Reviewed | Approved
> Authors: <names>
> Last updated: <date>

## 1. Problem statement
What we are solving, for whom, why now.

## 2. Scope
**In scope:** …
**Out of scope:** …

## 3. Quality attributes / NFRs
| Attribute | Target | Source |
|---|---|---|
| Availability | 99.9% | Operational SLA |
| P95 latency | < 300 ms | UX requirement |
| Throughput | 200 RPS sustained, 1000 RPS peak | Capacity model |
| RTO / RPO | 1h / 15min | Business continuity |
| Data residency | EU only | GDPR |
| Cost cap | €X / month | Budget |

## 4. Constraints
- Existing: …
- Team: …
- Regulatory: …
- Deadline: …

## 5. Solution overview
Narrative (3–6 paragraphs).

### 5.1 Context (C4 L1)
```mermaid
C4Context
…
```

### 5.2 Containers (C4 L2)
```mermaid
C4Container
…
```

### 5.3 Components (C4 L3) — for the most complex container
```mermaid
C4Component
…
```

## 6. Component responsibilities
| Component | Owns | Talks to | Tech |
|---|---|---|---|
| … | … | … | … |

## 7. Key flows
### 7.1 <Most important user journey>
```mermaid
sequenceDiagram
…
```

## 8. Identity & access
- Authentication: …
- Authorization model: …
- Secret management: Key Vault / managed identity / OIDC federated
- Service-to-service: managed identity + RBAC

## 9. Network topology  *(if applicable)*
- VNets / subnets
- Public vs private endpoints
- Ingress / egress
- DNS

## 10. Data architecture
- Stores: …
- Schema ownership: …
- Migration strategy: …
- Backup / retention: …

## 11. Operational concerns
- Telemetry: logs (Log Analytics workspace), metrics, traces (App Insights / OpenTelemetry)
- Top alerts: …
- Deployment strategy: blue/green | canary | rolling
- Runbooks: link

## 12. Failure modes & resilience
| Failure | Likelihood | Detection | Response |
|---|---|---|---|
| … | … | … | … |

## 13. Alternatives considered
### Option A: <chosen> — why
### Option B: <rejected> — why not
### Option C: <rejected> — why not

## 14. Cost band  *(if Azure)*
| Component | SKU | ~Monthly cost (€) |
|---|---|---|
| … | … | … |
| **Total** | | **€X – €Y / mo** |

## 15. Decisions (ADRs)
- [ADR-0001: …](../../adr/0001-….md)
- [ADR-0002: …](../../adr/0002-….md)

## 16. Open questions / risks
| # | Topic | Owner | Resolution by |
|---|---|---|---|
| 1 | … | … | … |
```

## 4. WAF walk-through (Azure designs)

Before declaring the design done, walk it through all five WAF pillars and write a one-paragraph self-assessment per pillar at the bottom of section 11 (Operational concerns) or as section 11a:

1. **Reliability** — zone/region redundancy, failure modes, RTO/RPO design.
2. **Security** — identity, secrets, network isolation, data protection at rest + in transit, threat surface.
3. **Cost optimization** — SKU choice, autoscale, reserved vs. consumption, lifecycle policies.
4. **Operational excellence** — IaC, CI/CD, observability, runbooks, alerting.
5. **Performance efficiency** — load testing, caching, async patterns, right-sized SKUs.

If a pillar has an accepted trade-off (e.g., "we accept lower availability for lower cost in dev"), say so explicitly.

## 5. Decision capture (ADRs are opt-in)

By default, capture decisions **inline** in arc42 §9 as a short table (decision · chosen option · rationale · reversible?) and surface trade-offs via the `trade-off-reporting` skill.

**Only delegate to the `architecture-decision-records` skill when the user explicitly asks** for an ADR / decision record / MADR. If you believe a decision is ADR-worthy (typically: choice of language/framework, data store, integration pattern sync vs. async vs. event-sourced, multi-tenancy model, identity provider, region/DR strategy, or anything irreversible / expensive to undo), **list it under "Suggested ADRs" in the hand-off** and let the user decide.

## 6. Diagram quality bar

- Use **C4 model** (Context → Container → Component) for structural diagrams.
- Use **Mermaid sequence diagrams** for flows.
- Every box has a name and a one-line responsibility.
- Every arrow has a label (`HTTPS/JSON`, `gRPC`, `AMQP`, `webhook`, etc.).
- Don't show implementation detail in a Context diagram or business actors in a Component diagram.

## 7. Hand off

**The calling agent's hand-off contract is the single definition of this block — this skill deliberately does not restate the field list.** `architect` declares the required fields of `ARCHITECTURE DESIGN COMPLETE` in its own definition and `dev-lead` gates on exactly those, so a second list here is how the two drift apart: a block that satisfies this file but not the agent reaches the orchestrator as a malformed hand-off with no visible cause.

Emit the block **your agent** specifies, and make sure this skill's output feeds it:

- the design artifacts you wrote → the deliverables field;
- the chosen approach and what it costs → the recommendation and trade-off fields;
- the NFRs from §4 → the NFR field, concrete and measurable;
- the decision section → the decisions-honoured field, and anything materially-shaping that is captured nowhere → the decision-gaps field (**you do not author ADRs** — a gap is surfaced for a human, never written up as one);
- **what you verified versus what you assumed** → the facts-verified and assumptions fields. The well-architected pass and the cost band above rest on service limits, tiers, regional availability and prices — exactly the facts that go stale between releases — so record each with its source and the date or version it applied to, and list anything you could not confirm as an assumption with its impact.

When a human invoked this skill directly and no agent contract is in play, report the same substance as a short summary: what you designed, what you recommend, what you verified, what you assumed, and what still needs a human decision. No orchestrator is parsing it, so the shape is free — the content is not.

## 8. What you do NOT do

- Don't write production code, IaC, or pipelines — that's the implementation agents.
- Don't promise NFRs the design can't deliver. Be honest about gaps.
- Don't pick irreversible choices unilaterally — present the alternatives.
- Don't commit — `architect` produces no code; the human decides when the document lands.

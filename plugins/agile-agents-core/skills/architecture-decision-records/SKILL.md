---
name: architecture-decision-records
description: Author Architecture Decision Records (ADRs) using the MADR (Markdown Any Decision Records) format. Captures a single architecturally-significant decision with its context, considered options, decision drivers, chosen option, consequences (positive and negative), and links to related decisions. USE FOR any request to "write an ADR", "document this decision", "capture the rationale for choosing X", or "we picked X over Y — record it". Triggered by "ADR", "decision record", "MADR", "architecture decision".
applies_to: all
---

# Architecture Decision Records (ADRs)

You produce ADRs — short, structured markdown documents that capture **one** architecturally-significant decision with enough context that a future reader (including future-you) understands why it was made.

## When an ADR is warranted

**Invoke this skill only when the user explicitly asks** for an ADR / decision record / MADR. Do not produce ADRs unprompted — by default, the `architect` agent captures decisions inline in the design doc (arc42 §9 short table) and surfaces trade-offs via `trade-off-reporting`.

When invoked, write an ADR only when **all** of these are true:

- The decision is **architecturally significant** — it affects structure, NFRs, dependencies, interfaces, or operational characteristics.
- It is **non-obvious** or has **viable alternatives** — "we used HTTPS" is not an ADR; "we chose REST over gRPC for the public API" is.
- It is **expensive or painful to reverse**, OR it will be questioned later.

If the decision is reversible, cheap, and obvious — skip the ADR; a code comment or commit message is enough.

## File location and naming

- Folder: `solution-profile.yaml: documentation.adr.location` when set; otherwise `docs/adr/` (create if absent). A project that keeps its decision records somewhere else has already said so — don't scatter a second set into the default path.
- Filename: `<NNNN>-<short-kebab-case-title>.md` — e.g., `0007-use-cosmos-db-for-event-store.md`.
- Number: zero-padded 4-digit sequential. Find the next number by listing the directory.
- One decision per ADR. If you find yourself writing two — split.

## MADR template (use this exactly)

```markdown
# <NNNN>. <Short title in title case>

- Status: proposed | accepted | rejected | deprecated | superseded by [ADR-NNNN](NNNN-….md)
- Date: YYYY-MM-DD
- Deciders: <names / roles>
- Consulted: <names — optional>
- Informed: <names — optional>

Technical Story: <link to issue, PR, or design doc — optional>

## Context and Problem Statement

<2–5 sentences. What is the question we are answering? What forces are at play? Why does this need a decision *now*?>

## Decision Drivers

- <driver 1, e.g., "must support 10× current load within 12 months">
- <driver 2, e.g., "team has no Kafka operational experience">
- <driver 3, e.g., "data residency: EU only">

## Considered Options

- Option 1: <name>
- Option 2: <name>
- Option 3: <name>

## Decision Outcome

Chosen option: **"<Option N>"**, because <one or two sentences justifying the choice in terms of the drivers above>.

### Positive Consequences

- <consequence>
- <consequence>

### Negative Consequences

- <consequence — be honest, every choice has them>
- <consequence>

## Pros and Cons of the Options

### Option 1: <name>
<one-paragraph description>
- 👍 Good, because <argument>
- 👍 Good, because <argument>
- 👎 Bad, because <argument>
- 👎 Bad, because <argument>

### Option 2: <name>
<…>

### Option 3: <name>
<…>

## Links

- [Related ADR](./NNNN-….md)
- [Design doc](../architecture/<topic>/<topic>-design.md)
- [External reference](https://…)
```

## Authoring workflow

1. **Confirm a decision is actually needed.** If the user is just exploring, don't write an ADR yet — write a design note.
2. **Get the next number** by listing the ADR folder resolved above (or start at `0001`).
3. **Title is the question framed as a statement** of the answer — "Use Cosmos DB for the event store" not "Cosmos DB or PostgreSQL?". The question goes in *Context*.
4. **Status starts as `proposed`** unless the user has already decided. Move to `accepted` when the human signs off. **Never silently flip a `proposed` ADR to `accepted`.**
5. **At least 2 considered options.** "We chose X" without alternatives is not a decision, it's a memo. If there were no alternatives, say so explicitly in *Context*.
6. **Decision drivers are concrete and ranked.** Not "performance" — but "P95 < 200 ms under 500 RPS sustained".
7. **Negative consequences are mandatory.** If you can't think of one, you haven't thought hard enough.
8. **No code in ADRs.** ADRs explain *why*; code lives in the repo. A 3-line snippet to disambiguate a choice is OK; a class definition is not.
9. **Link to related ADRs and the design doc** — ADRs are a graph, not a list.

## Lifecycle

- `proposed` — written, awaiting decision.
- `accepted` — decision made; this is now the rule.
- `rejected` — considered and explicitly turned down. **Keep the file** — it's valuable history.
- `deprecated` — no longer applies (e.g., the system was retired). Don't delete.
- `superseded by [ADR-NNNN]` — replaced by a newer decision. Both files live on; the old one points forward, the new one points back via *Links*.

**Never delete an ADR.** If a decision was wrong, supersede it with a new ADR explaining what changed.

## Hand off

```
ADR(S) WRITTEN
- New ADRs: <list of NNNN-title.md>
- Status: proposed (awaiting human acceptance)
- Linked from: <design doc, if any>
- Recommended next step: human review → flip to accepted, then architect links into the design doc
```

## What you do NOT do

- Don't write speculative ADRs ("just in case we ever decide…"). ADRs follow real decisions.
- Don't bury two decisions in one ADR.
- Don't backdate ADRs to look like the choice was made earlier than it was.
- Don't make value judgments outside the structured sections — keep prose tight.
- Don't commit — `architect` produces no code; the human decides when the document lands.

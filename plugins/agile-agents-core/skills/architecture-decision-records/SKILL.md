---
name: architecture-decision-records
description: Author Architecture Decision Records (ADRs) in whichever format the project declares — the `documentation.adr.format` key in solution-profile.yaml selects Nygard (Context / Decision / Consequences / Alternatives considered / References), MADR, a custom house shape, or none. Captures a single architecturally-significant decision with the forces behind it, what was chosen, what becomes true as a result (including the costs), which alternatives were rejected and why, and links to related decisions. USE FOR any request to "write an ADR", "document this decision", "capture the rationale for choosing X", or "we picked X over Y — record it". Triggered by "ADR", "decision record", "MADR", "architecture decision".
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

**Check `solution-profile.yaml: documentation.platform` first.** When it is anything other than `in-repo` (Confluence, a wiki, SharePoint, a separate repo), `adr.location` is a URL rather than a path — it cannot be listed, created, or written to. Produce the ADR body and state where a human must publish it (`<platform> → <location>`), and take the next number from the records already published there. Never fall back to writing files into the repo because the URL wasn't usable.

For an `in-repo` project:

- Folder: `solution-profile.yaml: documentation.adr.location` when set; otherwise `docs/adr/` (create if absent). A project that keeps its decision records somewhere else has already said so — don't scatter a second set into the default path.
- Filename: `<NNNN>-<short-kebab-case-title>.md` — e.g., `0007-use-cosmos-db-for-event-store.md`.
- Number: zero-padded 4-digit sequential. Find the next number by listing the directory.
- One decision per ADR. If you find yourself writing two — split.

## Resolve the format before writing

**`solution-profile.yaml: documentation.adr.format` decides the template.** The project has already declared how its decision records are shaped — read it rather than imposing a house style:

| `adr.format` | What to write |
|---|---|
| `nygard` | The Nygard template below — *Context → Decision → Consequences*, plus `Alternatives considered` and `References`. |
| `madr` | The MADR template below. |
| `custom` | The project has its own shape. **Read the two most recent ADRs in the folder and match them exactly** — headings, metadata block, title line. Impose neither template. |
| `none` | The project does not keep ADRs. Say so and stop; do not create a folder. |

**When the key is absent**, infer from the existing records — list the ADR folder and match the shape already in use. Only when the folder is empty or missing does `nygard` apply as the default, because it is the smaller commitment and the easier of the two to grow into.

A template that contradicts the project's own records is the failure mode to avoid here: it forks the convention, and the fork drifts.

## Nygard template

*Context → Decision → Consequences*, with two additions: an explicit `Alternatives considered` section, so a rejected option is recorded rather than implied, and `References`, so ADRs form a graph.

```markdown
# ADR <NNNN> — <what was decided, stated as the answer>

- **Status:** Proposed | Accepted | Rejected | Deprecated | Superseded by ADR <NNNN>
- **Date:** YYYY-MM
- **Deciders:** <names / roles (scope of the decision)>
- **Related:** ADR <NNNN> (<why it relates>), … — optional
- **Supersedes in part:** ADR <NNNN> (<exactly which part; the rest stands>) — optional

## Context

<2–5 sentences. What question are we answering, what forces are at play, and why does this need deciding *now*? Concrete drivers belong here — not "performance" but "P95 < 200 ms at 500 RPS sustained".>

## Decision

<What we are doing, stated plainly. One or two sentences of justification tied to the forces above. If the decision is conditional or gated on something, say so here.>

## Consequences

<What becomes true because of this — capability gained, cost incurred, constraint accepted. **Negative consequences are mandatory**; if you cannot name one, you have not thought hard enough.>

## Alternatives considered

<Each rejected option, what it was good for, and why it lost. "Rejected as insufficient" and "rejected as wrong" are different outcomes — say which. Note any option kept as a fallback.>

## References

<Related ADRs, design docs, external sources. Link both directions: when this supersedes or amends an earlier ADR, add the forward pointer to that ADR too.>
```

**Optional sections** may be added where the decision warrants them, placed before `Alternatives considered`: `Verification` (how the decision was proven out), `What was deliberately not changed` (to bound scope), `Not doing yet` (deferred follow-ons). An accepted ADR that later shifts gains an `Amendment (<date>)` section rather than a silent edit.

## MADR template

Use when `adr.format: madr`. Same discipline, different shape — drivers and per-option pros/cons are explicit sections rather than prose.

```markdown
# <NNNN>. <Short title in title case>

- Status: proposed | accepted | rejected | deprecated | superseded by [ADR-NNNN](NNNN-….md)
- Date: YYYY-MM-DD
- Deciders: <names / roles>
- Consulted: <names — optional>
- Informed: <names — optional>

Technical Story: <link to issue, PR, or design doc — optional>

## Context and Problem Statement

<2–5 sentences. What question are we answering, what forces are at play, why now?>

## Decision Drivers

- <driver — concrete, e.g. "P95 < 200 ms at 500 RPS sustained">

## Considered Options

- Option 1: <name>
- Option 2: <name>

## Decision Outcome

Chosen option: **"<Option N>"**, because <justification in terms of the drivers>.

### Positive Consequences

- <consequence>

### Negative Consequences

- <consequence — mandatory, every choice has them>

## Pros and Cons of the Options

### Option 1: <name>
<one-paragraph description>
- 👍 Good, because <argument>
- 👎 Bad, because <argument>

## Links

- [Related ADR](./NNNN-….md)
- [External reference](https://…)
```

## Authoring workflow

1. **Confirm a decision is actually needed.** If the user is just exploring, don't write an ADR yet — write a design note.
2. **Resolve the format** from `documentation.adr.format` (or from the existing records) before drafting, so the shape is right the first time.
3. **Get the next number** by listing the ADR folder resolved above (or start at `0001`).
4. **Title states the answer, not the question** — "Use Cosmos DB for the event store", not "Cosmos DB or PostgreSQL?". Follow the title line of the resolved template exactly (`# ADR 0007 — …` for Nygard, `# 0007. …` for MADR). The question itself goes in *Context*.
5. **Status starts at proposed** unless the user has already decided. Move to accepted when the human signs off, matching the casing the resolved template uses. **Never silently flip a proposed ADR to accepted.**
6. **At least 2 considered options.** "We chose X" without alternatives is not a decision, it's a memo. If there were no alternatives, say so explicitly in *Context*.
7. **Decision drivers are concrete and ranked** — not "performance" but "P95 < 200 ms under 500 RPS sustained". They live in *Context* under Nygard, in *Decision Drivers* under MADR.
8. **Negative consequences are mandatory.** If you can't think of one, you haven't thought hard enough.
9. **No code in ADRs.** ADRs explain *why*; code lives in the repo. A 3-line snippet to disambiguate a choice is OK; a class definition is not.
10. **Link to related ADRs and the design doc** — ADRs are a graph, not a list.

## Lifecycle

- `proposed` — written, awaiting decision.
- `accepted` — decision made; this is now the rule.
- `rejected` — considered and explicitly turned down. **Keep the file** — it's valuable history.
- `deprecated` — no longer applies (e.g., the system was retired). Don't delete.
- `superseded` — replaced by a newer decision. Both files live on; the old one points forward, the new one points back via *References* (Nygard) or *Links* (MADR). Record it in **both** directions — a one-way supersede leaves the old ADR looking current.

Match the casing of the resolved template (`Accepted` under Nygard here, `accepted` under MADR).

**Never delete an ADR.** If a decision was wrong, supersede it with a new ADR explaining what changed.

## Hand off

```
ADR(S) WRITTEN
- New ADRs: <list of NNNN-title.md>
- Status: Proposed (awaiting human acceptance)
- Linked from: <design doc, if any>
- Recommended next step: human review → flip to accepted, then architect links into the design doc
```

## What you do NOT do

- Don't write speculative ADRs ("just in case we ever decide…"). ADRs follow real decisions.
- Don't bury two decisions in one ADR.
- Don't backdate ADRs to look like the choice was made earlier than it was.
- Don't make value judgments outside the structured sections — keep prose tight.
- Don't commit — `architect` produces no code; the human decides when the document lands.

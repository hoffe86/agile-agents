# ADR 0010 — Extract the general-quality lens into a `code-review` agent; `review` becomes a pure orchestrator

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (review-topology split)
- **Related:** ADR 0009 (coding + testing merge — the *opposite* decision, for reasons that do not transfer), ADR 0007 (`model_tier` roster)

## Context

`review` did two jobs. It was the orchestrator of the review suite — triage which
lenses a diff warrants, dispatch the specialists, merge their reports, assign ids
and owners, issue one verdict — **and** it performed the general code-quality lens
itself: read every changed file in full and apply a large rubric (the pre-PR
mapping table plus a seventeen-row cloud-native anti-pattern table).

Every other lens (security, tests, architecture, infrastructure) was a pure
specialist. `review` was the only agent in the suite carrying two roles.

Three problems followed:

1. **A silent failure mode.** The two jobs compete for one heavy context, and they
   fail asymmetrically. Merging and verdict-writing are structurally load-bearing —
   they always get done, because the output is unusable without them. The
   line-by-line read is the part that quietly gets shallower as the diff grows.
   Nothing detects that: the report still arrives, still well-formed, still with a
   verdict. **A degraded general review is indistinguishable from a clean one.**
2. **The general lens was serial.** `review`'s own workflow read the whole diff and
   applied the rubric *before* fanning out. Four specialists then ran in parallel.
   One-fifth of the review work was serialised ahead of the rest for no reason
   other than who owned it.
3. **The general lens was not independently callable.** Every other lens can be
   invoked on its own. "Just give me a general quality review" required invoking
   the orchestrator, which then fanned out to security and the rest.

A fourth problem sat next to it. `read-repo-context` §3 instructed **every**
reviewing agent to load the `code-review` *skill* — which is a whole-repository
audit workflow that launches its own four parallel review agents, under a
**different severity scale** (`Critical/High/Medium/Low` vs
`Critical/Major/Minor/Nit`), **different finding ids** (`SEC-01` vs `C1`), and a
**different owner taxonomy** (🤖 Agent / 👤 User vs `coding` / `infrastructure` /
`architect`). Any reviewer that actually followed that instruction produced a
second, conflicting review that `dev-lead` could not route. `review` already
refused `code-review-checklist` for a milder version of the same conflict; nothing
refused the larger one.

## Decision

**Extract the general-quality lens into its own agent, `code-review`, and make
`review` a pure orchestrator.** The review suite becomes one merger over five
peer lenses:

| Agent | Role |
|---|---|
| `review` | triage → dispatch → merge → ids, owners, dedup → one verdict. **No lens of its own.** |
| `code-review` | general quality: correctness, line-level design, readability, standards, regressions, cloud-native anti-patterns, docs currency |
| `security-review` | unchanged |
| `test-review` | unchanged |
| `architecture-review` | unchanged |
| `infrastructure-review` | unchanged |

Supporting decisions:

1. **`code-review` and `security-review` are unconditional**; the other three stay
   triaged by diff signature. Every lens that doesn't run is reported *as not run*,
   with its reason — a reader must never have to guess whether "no findings" means
   clean or unchecked.
2. **`review` still reads the diff, at triage depth** — paths, file roles, size and
   shape. It needs that to route correctly and to sanity-check what comes back. It
   does not read every file in full; that is now `code-review`'s job.
3. **`code-review` reports an "Out of my lane" section** listing what it
   deliberately did not grade. `review` reconciles that against which specialists
   it invoked, so a mis-triage surfaces as a gap to close rather than shipping
   silently.
4. **The `code-review` skill is scoped to standalone whole-repository audits** and
   explicitly excluded inside the pipeline, with the conflicting conventions
   tabulated in the skill itself. `read-repo-context` no longer blanket-loads it.
5. **The agent takes the name `code-review`**, matching the existing
   `security-review` agent/skill precedent (both already coexist), and restoring
   the name the generalist reviewer carried before it absorbed orchestration —
   the reference in ADR 0007 that had been stale since.

## Why the ADR 0009 logic does not transfer

ADR 0009 merged `coding` and `testing` one change earlier. Applying that reasoning
here would argue for *fewer* review agents. It does not hold, and the difference is
worth stating precisely:

| | `coding` + `testing` (ADR 0009) | the review lenses (this ADR) |
|---|---|---|
| Coupling | **serial** — a hand-off round per task | **parallel** — read-only fan-out |
| Cost of the split | a full context transfer, every task | dispatch overhead only |
| What the split bought | nothing — independence lived downstream | **independence itself; it is the product** |
| Effect of merging | removes a real round-trip | removes a real check |

The entire cost driver in ADR 0009 was the serial hand-off. Reviewers have none.
Merging lenses here would pay no dividend and spend exactly what the arrangement
exists to produce.

## Consequences

**Positive**
- The general lens can no longer be silently starved by merge workload — the
  failure this ADR exists to remove.
- Five lenses run concurrently instead of one serial pass plus four parallel ones.
- The general lens is independently callable, like every other lens.
- Each context is smaller: the largest agent context in the suite (full diff +
  full rubric + four specialist reports) is split in two.
- The conflicting-conventions defect in the `code-review` skill is closed.
- `review`'s remaining rules are all genuinely about merging — dedup across lenses,
  id stability across rounds, owner routing — which were previously buried among
  rubric tables.

**Negative**
- **One more heavy-tier dispatch per review round** (≤2 rounds per run). The
  line-by-line work moves rather than duplicates, so the true added cost is
  dispatch overhead plus `review`'s triage-level second pass over the diff — but
  it is not zero, and on a small diff the split is pure overhead.
- 13 agents instead of 12; one more roster entry to keep consistent across the
  event-log enum, tier tables, and generated docs.
- Two artifacts now share the name `code-review` (agent and skill) doing different
  jobs. Mitigated by the scope boundary written into both, and by the
  `security-review` precedent — but it is a thing a newcomer must read once.
- A finding that spans two lenses (a logged secret is both quality and security)
  now arrives twice and must be merged. `review` owns that dedup explicitly; it
  was implicit before because one agent held both.

## Alternatives considered

- **Merge `test-review` into a combined general+test lens.** Rejected: it inverts
  the analysis above, and it would dilute `test-review` one change after ADR 0009
  made it load-bearing as the only independent check on author-written tests.
- **Leave the topology, fix only the skill conflict.** The high-confidence half of
  the win, and defensible — but it leaves the silent-degradation failure in place,
  which is the part that actually costs a missed finding.
- **Make `review` a thin merger that never reads the diff.** Rejected: it could
  then neither triage (routing needs the diff signature) nor notice a specialist
  report that contradicts the change. Triage-depth reading is the minimum viable
  input for the merger's job.
- **Fold triage into `dev-lead` and drop `review` entirely**, having the
  orchestrator dispatch five lenses directly. Rejected: merging, dedup and id
  stability across corrective rounds are a real job, and `dev-lead` is a
  `light`-tier orchestrator by ADR 0007 — this is `heavy` work.

## References

- `plugins/agile-agents-core/agents/code-review.agent.md` (the extracted lens)
- `plugins/agile-agents-core/agents/review.agent.md` (pure orchestrator; triage + merge rules)
- `plugins/agile-agents-core/skills/code-review/SKILL.md` (scope boundary table)
- `plugins/agile-agents-core/skills/read-repo-context/SKILL.md` §3 (blanket load removed)
- ADR 0009 (the opposite decision, and why it does not generalise), ADR 0007 (`model_tier`)

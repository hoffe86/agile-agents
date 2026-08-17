# ADR 0013 — Seniority is a shared skill plus role-specific judgement, not looser gates

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (agent authoring posture)
- **Related:** ADR 0009 (merged `coding`+`testing`), ADR 0010 (split the review lenses), ADR 0012 (data capability), ADR 0004 (cost envelope — the other place "just decide" is *not* allowed)

## Context

The roster was written as **procedure plus prohibition**. Measured across the 15 agents
(3061 lines) before this change:

- **Only `dev-lead` carried judgement** — an *Engineering judgement (the part that isn't
  process)* section and an *Autonomy contract*. The other **14 agents had neither**: each
  opened with a numbered `## Your job` list and closed with `## Hard rules`.
- **Prohibition was only ~5%** of agent text (154/3061 lines). The bulk was *procedure*.
  That is what made the agents behave juniorly: told the keystrokes, they followed steps
  instead of exercising the experience their own preamble claimed for them.
- **Interrogation was scattered** rather than concentrated at the gates that already exist.

Two artifacts showed the problem concretely rather than by assertion:

1. **`dev-lead` handled the same missing information two different ways.** Given a *plan
   file* with no acceptance criteria, Stage 0 derived candidates and confirmed them once.
   Given a *requirement* with no acceptance criteria, the same stage called it an ambiguity
   and stopped to ask. Same gap, opposite postures — and a plan-approval gate already
   existed to confirm at.
2. **`backlog-manager` contradicted itself.** Its Constraints said *"DO NOT create work
   items in the tracker without user confirmation of the draft"*, while its `dev-lead` Plan
   path requires creating child tasks **provisionally, tagged `pending-approval`, before**
   the Stage 4 gate. Read literally, the agent would ask for permission immediately before
   the gate built to ask for exactly that permission.

The request was for agents that behave like experienced practitioners — deciding rather
than checking in, and filling under-specified requests instead of bouncing them back.

## Decision

**Seniority is added as judgement, and paid for by deleting procedure — not by removing
gates.**

1. **A new core skill, `engineering-judgement`**, loaded silently on every turn by
   `read-repo-context` §3 alongside `engineering-standards`. The pairing is the point:
   `engineering-standards` is *what good looks like*; `engineering-judgement` is *how an
   experienced practitioner decides*. It carries: act inside your mandate without asking;
   escalate on **reversibility × blast radius** and never on unfamiliarity; fill
   under-specification with the professional default and label only the consequential
   calls; disagree in writing; right-size rigour; drop the theatre.
2. **Every agent gains a short role-specific "The calls only you make"** naming the
   judgement that role and no other exercises — the pattern `dev-lead` already used, and
   the same shape as the existing per-agent *"Apply engineering-standards to \<role\>"*
   anchors.
3. **Generic prohibitions were deleted** where the shared skill now covers them (*"Match
   existing conventions"*, *"Look it up rather than assume it"*), and `dev-lead`'s
   general-purpose judgement was folded into the shared skill, leaving only what
   supervising a run adds.
4. **Interrogation was consolidated at the gates that already exist.** Derived acceptance
   criteria — from a bare requirement *or* a plan file — are now confirmed in one place, a
   new **Acceptance criteria I derived** field on the Stage 4 plan-approval template.
5. **`backlog-manager`'s autonomy tiers were scoped** to the direct-invocation path, and
   the `dev-lead` Plan path made an explicit exception.
6. **The plan-approval gate was widened into the run's visibility point.** Deciding more
   only stays safe if the decisions become visible somewhere, and the gate a human actually
   reads had no slot for them — it relayed *Assumptions* and nothing else. `architect`
   already reports `Key tradeoffs`, `Open questions / risks` and `Decision gaps`; Stage 2
   already promised the human would see feasibility fallout "at Stage 4". None of it had a
   field. Added: **Trade-offs**, **Decisions I made that you may want to change**, **Risks
   and open questions**, and **What dies if a feasibility task returns ❌**, with an explicit
   relay-don't-digest rule and `none` defined as a claim rather than a default.
7. **`engineering-judgement` §6 ("Raise it early") front-loads the cost curve.** Without it,
   §1 (*don't ask*) and §5 (*right-size the effort*) read together as licence to skim
   Research and surface things late — the opposite of the intent. §6 states that
   right-sizing cuts **artifacts and ceremony, never the effort spent understanding the
   problem**, and that a consequential call belongs at the earliest gate someone could act
   on it. `dev-lead` Stage 1 carries the same rule concretely.

## What was deliberately *not* changed

**Every human gate stands.** Plan approval, PR approval, human-only merge/complete/close,
force-push and production-deploy bans, reviewer read-only, the test-asymmetry rule, and
the negative-result rules for `data-scientist` / `data-reviewer` are untouched. More
autonomy means *fewer questions*, not *fewer controls* — the two are routinely conflated
and the distinction is the whole content of this ADR.

`engineering-judgement` §8 exists to make that explicit in the place an agent actually
reads: seniority never licenses skipping verification, weakening a test, expanding scope,
inventing a fact, or routing around a gate because the change looked safe. Without §7 this
change would read as permission to be confident, which is the opposite of the intent.

**No autonomy profile key was added.** The obvious design — `autonomy_level: low | medium
| high` — was rejected. It is precisely the *"config knob for a value that never changes"*
that `dev-lead`'s own judgement rules reject, and the profile already declares blast radius
through `identity.lifecycle_stage` and `engagement_context.engagement_type`. The skill
reads those instead. A dial nobody turns is dead weight the harness has accumulated before
(`cicd.release_strategy` sat unread until `deploy-verify` became its first consumer).

**The stop-condition audit mostly vindicated the existing list.** Of `dev-lead`'s 13 stop
conditions, **12 were kept unchanged** — each is a one-way door or a gate a human owns.
Only #1 changed, from *"ambiguity surfaced mid-run"* to *"ambiguity that changes what is
being delivered"*, with an explicit carve-out that an undefined error semantic, a naming
question or a choice between equivalent libraries is decided and reported, not escalated.
That the other twelve survived is itself the finding: the over-escalation was in Stage 0
and in scattered prose, not in the stop list.

**Reviewer rubrics were not trimmed.** The temptation was to cut `code-reviewer`'s 60-line
working context and its anti-pattern table in the name of concision. That content is
*reference material the review needs*, not procedure the reviewer should have internalised;
removing it would produce a terser agent that finds less. Terse is not senior.

## Consequences

**The load-bearing pairing.** "Decide rather than ask" is only safe when paired with "and
expose the decision at the next gate". Taken alone, the first half produces a confident
black box — which is the failure this ADR is most likely to be blamed for if the pairing is
ever broken. §6 and the widened Stage 4 gate are that second half; **do not remove one
while keeping the other.** Autonomy is bought with visibility, not with trust.

**Positive**

- Judgement lives in one place and applies to all 15 agents, including any added later.
- The two self-contradictions above are resolved, and a run no longer pauses twice for one
  decision.
- Derived acceptance criteria now reach a human on **both** input paths through one field,
  where previously the requirement path stopped at Intake and only the plan path derived.
- Under-specified requests are handled rather than bounced, which is what the harness's
  users actually experience.

**Negative / accepted**

- **The agent files got longer, not shorter** (+305/−62 across 17 files), contrary to the
  original intent. Cutting procedure paid for the authoring agents, but the six review
  lenses had little procedure to remove — their `## Your job` lists were already three
  mechanical steps — so adding tailored judgement necessarily grew them. Accepted, because
  the alternative was hitting a line-count target by deleting rubric content, which trades
  review quality for tidiness.
- **The posture is unenforceable by CI.** No script can assert that an agent *decided*
  rather than *asked*. The invariant guard (below) proves nothing load-bearing was lost; it
  cannot prove the behaviour changed. Evidence will have to come from real runs.
- **Some risk of over-confidence.** Telling an agent to decide more will occasionally
  produce a wrong call that a question would have avoided. §7 and the unchanged gates are
  the mitigation; the labelling rule means such calls are at least written down where a
  reviewer sees them.

## Verification

Because this is a broad prose rewrite of behaviour-defining files, the guard is mechanical
rather than "we were careful". `capture-invariants.ps1` inventories the load-bearing
strings — all 7 sentinel block names and each of their fields, every profile key read,
every gate and boundary marker, agent frontmatter, sub-agent lists, and skill references —
before and after the rewrite. The baseline was itself mutation-tested (deleting one
hand-off field and one profile key was confirmed to show up in the diff) before being
trusted. Result: **542 → 561 invariant lines, none lost.**

## Alternatives considered

- **Shared skill only, agents untouched.** Small and low-risk, but the agents' own
  numbered `## Your job` lists would still say the opposite of the skill. Conflicting
  instructions in the same context window is not a posture change.
- **Relax the gates too** (auto-approve low-blast-radius plans, let agents open PRs).
  Rejected explicitly: it conflates "asks fewer questions" with "has fewer controls". The
  gates are what make autonomy safe enough to want.
- **Rewrite the agents without a shared skill.** Fifteen copies of the same posture, free
  to drift, with no single place to correct it.

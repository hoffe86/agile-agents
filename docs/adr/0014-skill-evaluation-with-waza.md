# ADR 0014 — Evaluate skills with Waza, as an S-layer beside the run-eval pyramid

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (skill quality measurement)
- **Related:** ADR 0008 (layered evaluation strategy — this sits beside it), ADR 0011 (reviewer naming — a regression from it was found by this work), ADR 0002 (self-benchmarking composition)

## Context

The harness ships **61 skills and no evidence that any of them work.**

ADR 0008 built a pyramid that grades **runs** — L0 trajectory (free, deterministic,
gating), L1 review-detection (deferred), L2 outcome (credit-heavy, manual). Nothing
in it grades the **artifacts**. Three failure modes were therefore invisible:

1. **Routing.** `description` is the *entire* selection mechanism — `copilot-instructions.md`
   states this, and notes that `applies_to` does **not** filter the candidate pool. Every
   installed skill competes on every task. Nothing measured whether the right one wins.
2. **Efficacy.** No skill had ever been compared against simply not loading it.
3. **Description collision.** The repo's own guidance is "keep descriptions specific enough
   that a wrong match is unlikely" — an instruction with no measurement behind it.

A fourth failure mode was not even suspected until the spike found it (below).

## Decision

**Adopt `microsoft/waza`** (MIT, Go, single binary, v0.38.6, active) as the skill-eval
runner, staged behind a spike, and structure it as an **S-layer** that sits *beside*
ADR 0008's pyramid rather than inside it.

| Tier | Grades | Cost | Gate? |
|---|---|---|---|
| **S0** | frontmatter validity, token budget, eval coverage | free, offline, deterministic | **yes — every push/PR** |
| **S1** | routing precision/recall (`skill_invocation`) | model | on demand |
| **S2** | efficacy A/B (`--baseline`: run with skills, then with skills stripped) | 2× model | manual |

L0/L1/L2 grade *runs*; S0/S1/S2 grade *skills*. Same doctrine as ADR 0008 — the free
deterministic tier gates, the expensive tiers stay manual.

**S0 is built now.** S1/S2 are specified and deferred (see *Not doing yet*).

### Why Waza

It is the only candidate whose **unit of evaluation is `SKILL.md` with YAML frontmatter** —
our format, and the `agentskills.io` standard's format. Verified by direct use, not from
its README:

- `waza check <path>` accepts `plugins/<plugin>/skills/<name>` directly, and
  `waza coverage --path` is repeatable — so the marketplace layout works without
  restructuring. (Bare `waza coverage` fails at our root: it looks for `skills/` or
  `.github/skills/`. Always pass `--path`.)
- `waza tokens check` honours `.waza.yaml` glob budgets.
- All of the above run **offline, instantly, with no model call and no Copilot token** —
  which is precisely what allows S0 to gate.

Its `skill_invocation` grader reads the **Copilot SDK's `SkillInvoked` events**. That
matters because it is telemetry the CLI does not persist: `~/.copilot/session-store.db`
logs shell commands and token usage and nothing about skill selection.

## What the spike found immediately

The tooling paid for itself before any eval suite existed.

**1. Three skills had invalid YAML frontmatter, and the CLI was silently dropping them.**
A plain (unquoted) YAML scalar may not contain a colon-space, and `ado-work-items`,
`artifact-coverage` and `github-issues` each embed one:

```yaml
description: ... Load only when `solution-profile.yaml: backlog.platform == x`.
```

This is not an inferred risk. The installed `agile-agents-core` v0.8.0 has **36 skills on
disk and offered exactly 35** to a live session; the one missing was `artifact-coverage`.
`ado-work-items` is the only skill in the installed `agile-agents-ado` plugin and was
likewise absent. Those skills **could never be invoked**, and nothing — not
`audit-references.ps1`, not the AGENTS.md generator, not review — noticed. `audit-references`
checks that referenced skills *exist as directories*; it never parses their frontmatter.

**2. ADR 0011's rename left behind the collision it was written to remove.** The
`-reviewer` rename changed the frontmatter `name:` of the `code-review` and
`security-review` **skills** to `code-reviewer` / `security-reviewer` while leaving their
directories as `-review`. AGENTS.md reads frontmatter, so the roster listed a *skill*
named `code-reviewer` alongside the *agent* `code-reviewer` — exactly the ambiguity ADR
0011 exists to prevent, and exactly the case its own reasoning says no name-based audit
can catch. `security-review` is vendored, so it was also an unsanctioned edit to a
vendored copy. Both restored.

Neither defect is exotic. Both are invisible on review, and both survived multiple PRs.

## Consequences

**Positive**

- Two classes of silent failure now fail the build instead of shipping:
  `scripts/check-skill-frontmatter.py` (strict YAML, name/directory agreement,
  required `applies_to`, with a `--self-test` that plants each defect and asserts it
  trips) and the `.waza.yaml` token ratchet.
- **Token cost is now visible.** A skill body enters context when it triggers, so size is
  recurring spend. The always-on set — `read-repo-context` + `engineering-standards` +
  `trade-off-reporting` + `engineering-judgement` — is **~8,100 tokens on every agent
  turn**, and ADR 0013 added 2,389 of that without anyone measuring it. Those four now
  carry the tightest ceilings in the repo.
- A baseline exists to improve against: **0/61 skills have an eval suite.**

**Negative / accepted**

- **A skill graded alone is not a skill in the pipeline.** Waza evaluates a skill in
  isolation; ours are consumed by a 15-agent RPI chain where `read-repo-context` pulls in
  three others silently. A skill can score well alone and still misbehave in the chain.
  **The S-layer complements L0/L2 and must never replace them.**
- **Waza is pre-1.0** (v0.38, ~6 months old, releasing every few days). Breaking changes
  are likely. Mitigated by coupling to a *binary and a YAML dialect*, never a library, and
  by the durability rule below.
- **The token limits are a ratchet, not a target.** They are set at today's measured cost
  so that regression fails; they do not bless current sizes. Raising one to go green is
  the metric gaming `engineering-judgement` §7 bans — trim the skill, or move detail into
  `references/`, which is loaded on demand rather than on trigger.
- One more moving part in CI, and a 135 MB binary to cache.

### Durability rule

**The eval task definitions are the durable asset; Waza is replaceable.** Author them
declaratively and free of Waza-only cleverness, and keep the field mapping to
`agentskills.io`'s `eval_queries.json` / `evals.json` documented, so that replacing the
runner is mechanical. If Waza stalls, we keep the corpus and change the runner.

## Alternatives considered

- **`agentskills.io` eval doctrine** — the specification behind our format publishes an
  official methodology (`eval_queries.json` with `should_trigger`, ~20 queries, 60/40
  train/validation split, near-miss negatives; `evals.json` for `with_skill/` vs
  `without_skill/` A/B with blind LLM judging). Stable, vendor-neutral, no dependency —
  **but it is a document, not a tool.** Retained as the durability target and the fallback.
- **promptfoo** (MIT, mature) — `exec: copilot …` treats our CLI as the system under test,
  A/B and LLM-judge first-class. Nothing in it understands `SKILL.md`, so every routing
  concept would be ours to build.
- **Inspect AI** (MIT, UK AISI) — best trajectory inspection, most Python boilerplate.
- **DeepEval** — `ToolCorrectnessMetric` aims well at routing, but CLI-as-SUT is friction
  and regression dashboards are hosted.
- **Rejected outright:** HELM (maintenance mode), AgentBench (wrong category), LangSmith /
  Braintrust (hosted), Azure AI Evaluation / OpenAI Evals (provider coupling), Promptbench
  (archived).
- **Build nothing and rely on review.** Rejected on evidence: review had already missed
  three dead skills and a reinstated naming collision.

## Not doing yet

- **S1 routing eval.** `skill_invocation` precision/recall over a pilot set. Needs model
  credits and a hand-authored query corpus per skill. Highest-value next tier, because
  routing is the failure mode with no other signal.
- **S2 efficacy A/B.** `waza run --baseline`. Most expensive, and most likely to produce
  an uncomfortable answer about skills that do nothing.
- **Description-collision analysis** across all 61 (including vendored, which we never edit
  but which still compete in the matching pool).
- **Live confirmation of skill naming under plugin delivery** — whether `skill_invocation`
  reports bare or plugin-namespaced names. Not load-bearing: the Copilot CLI emits skill
  loads as a `skill` tool call (`{"name":"skill","arguments":"{\"skill\":\"…\"}"}`, by bare
  name), so a Waza-independent fallback exists.

## References

- `.waza.yaml`, `scripts/check-skill-frontmatter.py`, `scripts/check-skill-tokens.ps1`
- `.github/workflows/skill-quality.yml` (S0, gating)
- `microsoft/waza` — https://github.com/microsoft/waza (MIT); grader docs under `docs/graders/`
- Agent Skills specification — https://agentskills.io/specification.md
- ADR 0008 (run-eval pyramid), ADR 0011 (reviewer naming), ADR 0013 (engineering judgement)

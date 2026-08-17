# `eval/skills/` — the S-layer

Grades **skills as artifacts**. Its sibling in `eval/` grades **runs**
([ADR 0008](../../docs/adr/0008-layered-evaluation-strategy.md)); this axis is
[ADR 0014](../../docs/adr/0014-skill-evaluation-with-waza.md). The two are orthogonal
and complementary — a skill can score perfectly here and still misbehave inside the
15-agent pipeline, which is what the L-layer is for.

Runner: [`microsoft/waza`](https://github.com/microsoft/waza) (MIT), whose unit of
evaluation is `SKILL.md` itself. No Azure, no AI Foundry — the executor enum is exactly
`copilot-sdk` and `mock`, and models come from a Copilot subscription.

| Tier | Directory | Grades | Cost | Gates? |
|---|---|---|---|---|
| **S0** | [`s0-routing/`](s0-routing/) | should this prompt reach this skill (offline heuristic) | free | reports only — threshold uncalibrated |
| **S1** | [`s1-invocation/`](s1-invocation/) | did the agent actually invoke it | model | manual |
| **S2** | [`s2-efficacy/`](s2-efficacy/) | is the outcome better *with* the skill than without | 2× model | blocked — see below |

Hygiene checks that also belong to S0 — frontmatter validity, the token ratchet, and the
`copilot-instructions.md` drift check — live in `scripts/` and run in the
[`skill-quality`](../../.github/workflows/skill-quality.yml) workflow. Those **do** gate;
they are deterministic and offline.

## Running each tier

```powershell
# S0 — free, offline, no auth. This is what CI runs.
./scripts/check-skill-tokens.ps1        # hygiene + coverage
./scripts/run-trigger-evals.ps1         # routing

# S1 — real model, needs Copilot auth
$env:GH_TOKEN = "<token with Copilot access>"     # or: copilot login
waza run eval/skills/s1-invocation/bicep-collision/eval.yaml -o results.json

# S2 — same, plus --baseline. Read s2-efficacy/README.md first; it does not
# currently produce a valid result on a machine with the plugins installed.
```

The S0 corpus is generated from authored prompts in
[`scripts/gen-trigger-evals.py`](../../scripts/gen-trigger-evals.py) — edit the prompts
there and regenerate, rather than hand-editing the YAML.

## What each tier has found

- **S0** — 14/61 skills covered, routing 30/35. Flagged 3 "false triggers" where one
  skill looked likely to answer for another.
- **S1** — tested two of those three against ground truth. **Both were heuristic
  artifacts**: the agent routed correctly. More importantly, on one task it completed the
  work perfectly while invoking **no skill at all**.
- **S2** — attempted; blocked on environment isolation, not credits.

The through-line: **S0 over-reports collisions, and the real risk is skills being
bypassed rather than confused.** That is why no description has been rewritten on S0
evidence alone, and why S2 matters more than it originally looked.

## The trap to remember

S2's first run reported *"skills have negative/neutral impact (100.0% vs 100.0%)"* — a
believable number that was pure artifact, because the skills-stripped pass had the skill
too. **A contaminated baseline does not error.** Before trusting any A/B delta, confirm
the control pass invoked nothing.

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
| Hygiene | `scripts/` | frontmatter, token ratchet, instructions drift | free | yes — deterministic and offline |
| Outcome | [`outcome/plan/`](outcome/plan/) | plan artifact for one data-feasibility scenario | model | manual, not an A/B comparison |
| **S2** | [`s2-efficacy/`](s2-efficacy/) | historical A/B attempt | 2× model | not runnable against current core; isolation also required |

Only hygiene runs in the [`Eval · skills`](../../.github/workflows/eval-skills.yml)
workflow. Token size and the coverage inventory are not skill-quality results.

Routing (S0) and invocation (S1) suites were removed: they measured whether
GitHub Copilot selects or invokes a skill, which is host behavior, not ours. We test
our own artifacts and phase gates; see `scripts/tests/`.

## Running each tier

```powershell
# Free, offline, no auth. CI runs this alongside frontmatter and drift checks.
./scripts/check-skill-tokens.ps1

# Manual, model-backed outcome check, run from the repository root.
waza run eval/skills/outcome/plan/eval.yaml --no-update-check
```

The outcome suite injects the current `plan` body and checks the
produced plan file; it does not grade skill selection or invocation. Its
execution sends the skill and synthetic prompt to the configured model provider;
run it only where that disclosure is permitted. Its deterministic patterns
check the specified ownership, dependency, criterion
mapping, approval and acceptance markers, not the full semantic quality of the
plan. It is not evidence that the skill improves results over a baseline.
The synthetic scenario explicitly enables data science and makes its agent
available; it does not use this repository's disabled data-science setting.
Research and Implement do not yet have outcome suites. The coverage report is
an inventory of suite definitions, not proof that they ran or passed; Waza's
full/partial classification is based on suite structure, not outcome quality.

The remaining technical S2 suite requires its absent consumer target and a
verified isolated baseline. Custom-eval uses its own minimal explicit inputs,
not a skill library. See [ownership](../../docs/customization-ownership.md).

## Historical findings before retirement

- **S0** — 14/61 skills covered, routing 30/35. Flagged 3 "false triggers" where one
  skill looked likely to answer for another.
- **S1** — tested two of those three against ground truth. **Both were heuristic
  artifacts**: the agent routed correctly. More importantly, on one task it completed the
  work perfectly while invoking **no skill at all**.
- **S2** — attempted; blocked on environment isolation, not credits.

These observations are historical, not evidence about the current phase skills.

## The trap to remember

S2's first run reported *"skills have negative/neutral impact (100.0% vs 100.0%)"* — a
believable number that was pure artifact, because the skills-stripped pass had the skill
too. **A contaminated baseline does not error.** Before trusting any A/B delta, confirm
the control pass invoked nothing.

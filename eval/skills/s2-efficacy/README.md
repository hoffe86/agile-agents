# `s2-efficacy/` — efficacy A/B (blocked on environment isolation)

**Status: cannot produce a valid result on a machine with the plugins installed.**
Not blocked on credits — blocked on isolation. Read this before running anything here.

## What S2 is for

`waza run --baseline` executes every task twice — once with skills loaded, once with
them stripped — and reports the delta. It is the only tier that answers *"does this skill
actually improve the outcome, or is it decoration?"*, which S1 made urgent by showing an
agent complete a task correctly while invoking no skill at all.

## Why it does not currently work here

The first run looked clean and was meaningless:

```
baseline comparison: skills have negative/neutral impact (100.0% vs 100.0%)
```

Checking the run detail rather than the headline: **the skills-stripped pass invoked
`update-avm-modules-in-bicep` too.** Both halves of the A/B had the skill, so the
comparison was skills-on versus skills-on, and the identical scores mean nothing.

Confirmed by escalating to the explicit flag — `waza run --no-skills` **still** shows the
skill being invoked. The source is the developer's own globally installed plugins:

```
~/.copilot/installed-plugins/agile-agents-marketplace/agile-agents-bicep/skills/
    azure-deployment-preflight
    bicep-implementation
    update-avm-modules-in-bicep
```

Waza's embedded Copilot CLI loads those regardless of `skill_directories` or
`--no-skills`. Waza can add skills to a run; it cannot subtract the ones the CLI already
has.

**This is the trap worth remembering:** the failure is invisible in the summary line. A
contaminated baseline reports a plausible number — *"skills have neutral impact"* — that
reads like a finding and is actually an artifact. Always check that the baseline pass
invoked nothing before believing a delta.

## How to get a valid result

Run S2 where the plugins are **not installed**:

- a clean container or CI runner that has never run `copilot plugin install`, or
- a machine after `copilot plugin uninstall` for every `agile-agents-*` plugin, or
- a separate user profile with its own `~/.copilot`.

Then verify isolation *before* trusting any delta: run one task with `--no-skills` and
confirm `session_digest.tool_calls` contains **no** `skill` entries. Only then is the
baseline a baseline.

## Does this invalidate S1?

**No.** S1's conclusions do not depend on removing skills:

- The bicep collision test asked *which* skill gets invoked — it fired 3/3 correctly.
  Where the skill came from does not change that.
- The python collision test found **no skill invoked at all** — and that result is now
  *stronger*, not weaker: `pytest-coverage` was both globally installed **and** injected
  via `skill_directories`, and the agent still bypassed it.

Only S2, which depends on a skill-free control, is affected.

## The suite here

`avm-bump-efficacy/` is written and correct — outcome-graded via the `file` grader (did
both AVM pins actually move, with the module references and parameters intact) rather
than `skill_invocation`, which would trivially fail the stripped pass and measure nothing.
It is ready to run the moment an isolated environment exists.

One caveat to fix at the same time: the grader checks that the versions *changed*, not
that they are *correct*. A skill could plausibly add accuracy that this grader cannot
see. Tighten it to assert the resolved versions before drawing conclusions about value.

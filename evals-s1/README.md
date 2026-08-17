# `evals-s1/` — observed-invocation evals (S1)

**Not free, not in CI.** These call a real model through Waza's `copilot-sdk` executor.
S0 (`evals/`) is the offline heuristic tier that gates; this is the ground-truth tier
that tells you whether the heuristic was right. See
[ADR 0014](../docs/adr/0014-skill-evaluation-with-waza.md).

## Running them

```powershell
$env:GH_TOKEN = "<a GitHub token with Copilot access>"   # or: copilot login
waza run evals-s1/bicep-collision/eval.yaml -o results.json
```

Waza uses **its own embedded Copilot CLI** (`%LOCALAPPDATA%\copilot-sdk\`), not the one
on your PATH, and refuses to start unauthenticated. There is no Azure or AI Foundry
dependency — the executor enum is exactly `copilot-sdk` and `mock`, and models come from
your Copilot subscription.

## Two things that cost a run to learn

**Fixtures use `inputs.context.fixture`, not `inputs.files`.** The first attempt used
`files:` and all three trials landed in an *empty* temp workspace, globbed, found nothing
and asked for the file. `files:` is a resource reference; `context.fixture` is the key
that copies a file or directory into the workspace before the agent starts.

**Skills are addressed by bare name.** Even though they are delivered through a plugin
marketplace, `skill_invocation` matches `update-avm-modules-in-bicep`, not
`agile-agents-bicep:update-avm-modules-in-bicep`. Confirmed by asking an agent to list
its available skills: all 61 came back unqualified.

## What these two suites found

Both target collisions that S0's offline heuristic flagged as **false triggers** — cases
where it predicted one skill would answer for another.

### `bicep-collision` — the heuristic was wrong

S0 scored `bicep-implementation` **0.80** on *"bump every AVM module"* (its partner's job)
and **0.38** on its own authoring case — an inverted profile that looked like a badly
mis-tuned description.

Observed: **3/3 trials invoked `update-avm-modules-in-bicep`**, the correct skill.
`bicep-implementation` never fired.

So the S0 signal was an artifact. The heuristic compares description *vocabulary*; the
model has the actual file and task shape and disambiguates easily. **This is why the
routing suite reports instead of gating, and why no description was rewritten on S0
evidence alone** — doing so would have "fixed" a skill that was never broken.

### `python-collision` — a better question than the one asked

S0 scored `python-testing` 0.71 on a coverage-closing request (`pytest-coverage`'s job).

Observed: **no skill was invoked at all** — in any of 3 trials. The agent explored the
fixture, ran coverage, found 13%, wrote 25 tests and reached 100%. It did the job
correctly and never reached for `pytest-coverage`, `python-testing` *or*
`testing-practices`.

That is a more uncomfortable result than a wrong skill firing, and it reframes the
collision question entirely: **the risk is not that skills compete, it is that they are
bypassed.**

### The hypothesis worth testing next

Comparing the two: the bicep task needed knowledge the model lacks (which AVM versions
are current — it used `web_fetch`), and the skill fired. The pytest task needed nothing
the model cannot already do, and no skill fired.

**Skills may get invoked when they carry knowledge the model lacks, and skipped when the
model can already do the task.** If that holds across the library, a large part of a
61-skill collection is inert on the tasks it was written for — which is precisely what S2
(`waza run --baseline`) exists to measure. Treat it as a hypothesis with two datapoints,
not a conclusion.

## Cost, for planning

Roughly, at `claude-haiku-4.5`, 3 trials of one task with a small fixture:

| Suite | Premium requests | Total tokens |
|---|---|---|
| `bicep-collision` | 8 | ~947k |
| `python-collision` | ~9 | ~1.19M |

Most of that is cache reads, but the per-task cost is real. Scale deliberately.

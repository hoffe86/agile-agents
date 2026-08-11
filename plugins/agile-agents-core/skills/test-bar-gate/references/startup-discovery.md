# Startup discovery — finding how to run the project

Used by the **smoke** slot of `test-bar-gate` when `solution-profile.yaml: testing.smoke.command`
is empty. The goal is a *derived* start command and health URL, not a guessed one: everything
below reads something the project already declares.

This file is **technology-neutral by design**. The ecosystem-specific rules live in the companion
plugin for that ecosystem, so a project installs only what it uses — see *Route to the ecosystem
skill* below.

## Resolution order

Stop at the first that answers:

1. **The profile** — `testing.smoke.command` + `url`. Explicit beats derived, always.
2. **The project's own declared start command.** Neutral evidence, true in any language: a
   `Procfile` `web:` line, a `Dockerfile` `CMD` / `ENTRYPOINT`, a compose service `command:`, or a
   documented run command in the README or the CI workflow. This is the team stating how they
   actually run it, and it outranks any convention.
3. **The ecosystem skill** for the declared stack (below), which knows that ecosystem's entry
   points and defaults.
4. **Research** — per `read-repo-context` §9, when the above leave it ambiguous.
5. **Stop and report.** Emit `outcome=skipped, reason=undetermined` naming what you inspected, and
   recommend setting `testing.smoke.command`. Never invent a plausible command — a wrong one burns
   the full timeout and reports a startup failure that is really a configuration failure.

## Route to the ecosystem skill

Route on **skill availability, not technology name** — the companion plugins are optional:

| Declared stack | Skill | Ships in |
|---|---|---|
| .NET / C# | `dotnet-startup-discovery` | `agile-agents-dotnet` |
| Python | `python-startup-discovery` | `agile-agents-python` |

**If the matching skill is not installed** — or the stack is one no companion covers — work from
step 2's neutral evidence and the repo's own conventions, then report `undetermined` if that still
does not answer. Say in the gate result that no ecosystem skill was available, so the gap reads as
a missing plugin rather than an unstartable application. Never hardcode a stack's entry-point rules
back into this file: that is what the companion plugins are for.

## Nothing to start — a first-class answer

Some changes have nothing to start, and detecting that beats timing out against it. The neutral
case: **the diff touched only docs, IaC, or pipeline definitions.** Ecosystem-specific cases (a
class library, a package with no entry point) are decided by the skill for that stack.

Emit `outcome=skipped, reason=not_applicable, detail=<what you looked for>`. This is a pass, but a
*stated* one: "there is nothing to start here" and "I could not work out how to start it" are
different claims and must not report identically.

## Reporting what you derived

Whatever you resolve, put it in the gate output — the command, the URL, and which rule above
produced it — then feed it back to the runner via `--smoke-command` / `--smoke-url` so the
start/poll/stop logic has exactly one implementation.

A derived command that worked is worth writing into `testing.smoke.command` so the next run is
deterministic instead of re-deriving; recommend that in the gate result rather than editing the
profile yourself.

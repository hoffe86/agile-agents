# Startup discovery — finding how to run the project

Used by the **smoke** slot of `test-bar-gate` when `solution-profile.yaml: testing.smoke.command`
is empty. The goal is a *derived* start command and health URL, not a guessed one: everything
below reads something the project already declares.

This file is **technology-neutral by design**. Concrete startup guidance belongs
to the solution's native instructions, local skills or selected external plugins.

## Resolution order

Stop at the first that answers:

1. **The profile** — `testing.smoke.command` + `url`. Explicit beats derived, always.
2. **The project's own declared start command.** Neutral evidence, true in any language: a
   `Procfile` `web:` line, a `Dockerfile` `CMD` / `ENTRYPOINT`, a compose service `command:`, or a
   documented run command in the README or the CI workflow. This is the team stating how they
   actually run it, and it outranks any convention.
3. **Applicable available solution capability** (below), which interprets actual
   entry-point evidence, not a language default.
4. **Research** — per `read-repo-context` §9, when the above leave it ambiguous.
5. **Stop and report.** Emit `outcome=fail, reason=undetermined` naming what you inspected, and
   recommend setting `testing.smoke.command`. Never invent a plausible command — a wrong one burns
   the full timeout and reports a startup failure that is really a configuration failure.

## Route to the ecosystem skill

Use `read-repo-context` discovery to match available descriptions/capabilities to
startup for the actual stack/version and path. Arbitrary names are valid; no
companion catalog. Preserve native instruction scopes. On-disk is not runtime
availability; diagnose absent or ungranted before recommending setup.

Without matching optional depth, use step 2's evidence and repo conventions,
then report `undetermined` if still unresolved. Report the fallback as missing
guidance/access, not proof of an unstartable app or a required plugin. Never
hardcode stack entry-point rules here or invent a command.

## Smoke timing prerequisites

Bash smoke deadlines use subsecond timestamps, not rounded Unix seconds. This
requires Bash 5+ (`EPOCHREALTIME`) or a `date` implementation supporting `%N`.
If neither is available, the runner reports a configuration gap before launch.
Requests and polling waits share the same deadline; a late response cannot pass.

## Nothing to start — a first-class answer

Confirm the project/component being verified has no runnable entry point.
A docs-only diff alone does not prove that; use the supervisor's applicability
rules, not a smoke exemption that contradicts a configured startup command.

Supply `--smoke-status not_applicable --smoke-detail "<what you looked for>"`
(PowerShell: `-SmokeStatus` / `-SmokeDetail`). This is a visible skip, not a
startup pass. Unknown setup uses `undetermined` with evidence and exits 2.
Do not use non-applicability for a runnable app with missing prerequisites.

## Reporting what you derived

Whatever you resolve, put it in the gate output — the command, the URL, and which rule above
produced it — then feed it back to the runner via `--smoke-command` / `--smoke-url` so the
start/poll/stop logic has exactly one implementation.

A derived command that worked is worth writing into `testing.smoke.command` so the next run is
deterministic instead of re-deriving; recommend that in the gate result rather than editing the
profile yourself. No HTTP surface requires a solution-owned readiness adapter;
without one, startup is unverified. Never assume a framework port or health path.

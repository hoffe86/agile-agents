---
name: dotnet-startup-discovery
description: Work out how to start a .NET application and which URL proves it came up — Aspire AppHost, Azure Functions, ASP.NET Core web projects, console/worker services — by reading what the project already declares (project SDK, OutputType, launchSettings.json, health-check registration). USE FOR the smoke slot of `test-bar-gate` when `testing.smoke.command` is not configured, or any request to "run the app", "start the API", "check it boots", "which project do I run" in a .NET repo. Also detects when there is nothing to start (class library, analyzer, shared contracts).
applies_to: dotnet
---

# .NET startup discovery

Answers one question: **what command starts this application, and what URL proves it came up?**

The `test-bar-gate` smoke slot loads this when the profile does not declare
`testing.smoke.command`. Everything below reads something the project already states — this is
discovery, not guessing. A wrong command burns the gate's full timeout and reports a startup
failure that is really a configuration failure, so where the signals run out, stop and say so
rather than picking a plausible candidate.

## Pick the entry point

First match wins — each row is more specific than the one below it.

| Signal | Start command | Why it ranks here |
|---|---|---|
| `*.AppHost/*.csproj` (Aspire) | `dotnet run --project <AppHost.csproj>` | The AppHost starts the whole service graph, so it is the truest "does it come up". Prefer it even when a web project is also present. |
| `host.json` + a Functions SDK reference | `func start` | Functions do not boot via `dotnet run`. If Azure Functions Core Tools is absent, that is a tooling gap — report it as such, not as a startup failure. |
| `.csproj` with `Sdk="Microsoft.NET.Sdk.Web"` | `dotnet run --project <csproj>` | The common web/API case. |
| `.csproj` with `<OutputType>Exe</OutputType>` | `dotnet run --project <csproj>` | Console or worker service. |

**Several candidates?** Prefer the startup project the `.sln` declares, then the one the current
diff actually touched. If two web projects remain and nothing distinguishes them, that is
`undetermined` — name the candidates you found instead of choosing one.

`dotnet run` restores and builds on its own. `--no-build` is worth adding when the gate's typecheck
slot has just built the same configuration, and worth dropping the moment it produces a
stale-binary confusion.

## Resolve the URL

1. `Properties/launchSettings.json` → the profile's `applicationUrl`. **Take the `http://` entry
   over `https://`**: an untrusted dev certificate fails the poll in a way that looks exactly like
   the app not starting, and diagnosing that costs more than the check saves.
2. `ASPNETCORE_URLS`, if set in the environment or in `launchSettings.json`.
3. Otherwise the Kestrel default `http://localhost:5000`. Functions default to `http://localhost:7071`.

**Path** — `/health` when the app registers health checks (`AddHealthChecks` / `MapHealthChecks`),
otherwise `/`. Any HTTP status below 500 counts as up, so an unauthenticated `401` at `/` is a
pass: the host answered, which is the whole question.

**A port conflict is not a startup failure**, but it does invalidate the result — the poll may hit
an unrelated process already on that port and pass. If the port is held before you start, say so
rather than trusting what comes back.

## No HTTP surface

A worker service, queue consumer or scheduled job has nothing to poll. Start it, confirm it is
still alive after a few seconds and did not exit non-zero, and report that as the check. A
crash-on-boot from bad DI wiring still surfaces — which is the failure the smoke slot exists to
catch, and it needs no endpoint to be visible.

## Nothing to start

Report `not_applicable` — naming what you looked for — when the solution has no project with
`<OutputType>Exe</OutputType>` and no `Microsoft.NET.Sdk.Web` project: a class library, an
analyzer or source generator, a shared-contracts package, a test-only project.

"There is nothing to start here" and "I could not work out how to start it" are different claims.
Never report them identically.

## Hand back

Return the command, the URL, and which rule above produced them, so the gate can run it and the
run's report can show where it came from. When it works, recommend writing it into
`solution-profile.yaml: testing.smoke.command` so the next run is deterministic instead of
re-deriving. Recommend it; do not edit the profile yourself.

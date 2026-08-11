# Startup discovery — finding how to run the project

Used by the **smoke** slot of `test-bar-gate` when `solution-profile.yaml: testing.smoke.command`
is empty. The goal is a *derived* start command and health URL, not a guessed one: everything
below reads something the project already declares.

Resolution order — stop at the first that answers:

1. **The profile** — `testing.smoke.command` + `url`. Explicit beats derived, always.
2. **The project's own declared start command** (below). A `Procfile`, a `Dockerfile` `CMD`, a
   compose `command:`, or a launch profile is the team telling you how they run it.
3. **Stack conventions** (below), from the entry point actually present in the repo.
4. **Research** — per `read-repo-context` §9: the repo's `README`, its CI workflow (what does the
   pipeline run to start it?), then documentation tooling for the framework in question.
5. **Stop and report.** Emit `outcome=skipped, reason=undetermined` naming what you inspected, and
   recommend setting `testing.smoke.command`. Never invent a plausible command — a wrong one burns
   the full timeout and reports a startup failure that is really a configuration failure.

## Not applicable — a first-class answer

Some projects have nothing to start. Detect this rather than timing out against it:

- **.NET** — no project with `<OutputType>Exe</OutputType>` and no `Microsoft.NET.Sdk.Web` project
  in the diff's solution: a class library. Also: analyzers, source generators, shared contracts.
- **Python** — a package with no `[project.scripts]`, no `__main__.py`, and no ASGI/WSGI app object.
- **Any stack** — the diff touched only docs, IaC, or pipeline definitions.

Emit `outcome=skipped, reason=not_applicable, detail=<what you looked for>`. This is a pass, but a
*stated* one: "there is nothing to start here" and "I couldn't work out how to start it" are
different claims and must not report identically.

## .NET

Pick the entry point in this order — the first match wins, because each is more specific than the
next:

| Signal | Start command | Notes |
|---|---|---|
| A `*.AppHost/*.csproj` (Aspire) | `dotnet run --project <AppHost.csproj>` | Prefer it: the AppHost starts the whole service graph, so it is the truest "does it come up". |
| `host.json` + a Functions SDK reference | `func start` | Needs Azure Functions Core Tools; if absent, that is a `not_determined` tooling gap, not a startup failure. |
| `.csproj` with `Sdk="Microsoft.NET.Sdk.Web"` | `dotnet run --project <csproj>` | The common web/API case. |
| `.csproj` with `<OutputType>Exe</OutputType>` | `dotnet run --project <csproj>` | Console / worker service. A worker with no HTTP surface has no URL — see below. |

**Several candidates?** Prefer the startup project the solution declares, then the one the diff
actually touched. If two web projects remain and nothing distinguishes them, that is
`undetermined` — say which candidates you found rather than picking one.

**Health URL** — `Properties/launchSettings.json` → the first `applicationUrl` (take the `http://`
entry over `https://` to avoid dev-certificate trust failures, which look like startup failures and
are not). Otherwise `ASPNETCORE_URLS`, otherwise the Kestrel default `http://localhost:5000`;
Functions default to `http://localhost:7071`.

**Path** — `/health` when the code registers health checks (`AddHealthChecks` / `MapHealthChecks`),
otherwise `/`. Any HTTP status < 500 counts as up, so an unauthenticated `401` on `/` is a pass:
the host answered, which is what this slot asks.

**No HTTP surface** (worker service, queue consumer)? There is nothing to poll. Start it, confirm
it stays alive for a few seconds without exiting non-zero, and report that as the check — a
crash-on-boot from bad DI wiring still surfaces, which is the failure this slot exists to catch.

## Python

| Signal | Start command |
|---|---|
| `pyproject.toml` → `[project.scripts]` / `[tool.poetry.scripts]` | the declared console script |
| FastAPI / Starlette app object | `uvicorn <module>:<app>` (default `http://localhost:8000`) |
| Flask app object | `flask --app <module> run` (default `http://localhost:5000`) |
| `manage.py` (Django) | `python manage.py runserver` (default `http://localhost:8000`) |
| `__main__.py` in the package | `python -m <package>` |

**Prefer what the repo already declares** over the table above: a `Procfile` `web:` line, a
`Dockerfile` `CMD` / `ENTRYPOINT`, or a compose service `command:` is the project's real answer, and
the table is only for when none of those exist.

**Run it the way the project manages environments** — `uv run …` / `poetry run …` / `pipenv run …`
when the repo uses one (lockfile present), otherwise the bare command. Ignoring the environment
manager is the most common cause of a spurious `ModuleNotFoundError` at this gate.

**Health path** — a declared health/readiness route when one exists, otherwise `/`. Same rule as
.NET: any status < 500 is up.

## Reporting what you derived

Whatever you resolve, put it in the gate output — the command, the URL, and which rule above
produced it. A derived command that worked is worth writing into `testing.smoke.command` so the
next run is deterministic instead of re-deriving; recommend that in the gate result rather than
editing the profile yourself.

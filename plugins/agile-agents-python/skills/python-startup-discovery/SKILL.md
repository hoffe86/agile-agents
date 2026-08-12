---
name: python-startup-discovery
description: Work out how to start a Python application and which URL proves it came up — console scripts, FastAPI/Starlette, Flask, Django, `python -m <package>` — by reading what the project already declares (pyproject scripts, app objects, Procfile, Dockerfile CMD, compose command) and running it through the project's own environment manager. USE FOR the smoke slot of `test-bar-gate` when `testing.smoke.command` is not configured, or any request to "run the app", "start the server", "check it boots", "how do I run this" in a Python repo. Also detects when there is nothing to start (a library with no entry point).
applies_to: python
---

# Python startup discovery

Answers one question: **what command starts this application, and what URL proves it came up?**

The `test-bar-gate` smoke slot loads this when the profile does not declare
`testing.smoke.command`. Everything below reads something the project already states — this is
discovery, not guessing. A wrong command burns the gate's full timeout and reports a startup
failure that is really a configuration failure, so where the signals run out, stop and say so
rather than picking a plausible candidate.

## What the project already declares beats any convention

Check these first. Each is the team stating how they actually run the thing:

- `Procfile` → the `web:` process line.
- `Dockerfile` → `CMD` / `ENTRYPOINT`.
- `docker-compose.yml` → the app service's `command:`.
- `pyproject.toml` → `[project.scripts]` or `[tool.poetry.scripts]`.

## Otherwise, infer from the entry point

| Signal | Start command | Default URL |
|---|---|---|
| FastAPI / Starlette app object | `uvicorn <module>:<app>` | `http://localhost:8000` |
| Flask app object | `flask --app <module> run` | `http://localhost:5000` |
| `manage.py` (Django) | `python manage.py runserver` | `http://localhost:8000` |
| `__main__.py` in the package | `python -m <package>` | — (often no HTTP surface) |

## Run it the way the project manages environments

`uv run …`, `poetry run …`, `pipenv run …`, or an activated venv — pick whichever the repo's
lockfile implies (`uv.lock`, `poetry.lock`, `Pipfile.lock`). **Ignoring the environment manager is
the single most common cause of a spurious failure at this gate**: the bare command raises
`ModuleNotFoundError` for a dependency that is installed perfectly well inside the managed
environment, and the gate reports a startup failure that does not exist.

## Health path

A declared health/readiness route when the app has one, otherwise `/`. Any HTTP status below 500
counts as up — an unauthenticated `401` is a pass, because the server answered, which is the whole
question.

An ASGI/WSGI app with no route at `/` will answer `404`, which is also a pass for the same reason:
the process bound the port and served a response.

## No HTTP surface

A CLI, worker or consumer has nothing to poll. Start it, confirm it is still alive after a few
seconds and did not exit non-zero, and report that as the check — an import-time crash or a bad
settings load still surfaces, which is what the slot is for.

## Nothing to start

Report `not_applicable` — naming what you looked for — when the package declares no
`[project.scripts]`, has no `__main__.py`, and exposes no ASGI/WSGI app object: a library.

"There is nothing to start here" and "I could not work out how to start it" are different claims.
Never report them identically.

## Hand back

Return the command, the URL, and which rule above produced them, so the gate can run it and the
run's report can show where it came from. When it works, recommend writing it into
`solution-profile.yaml: testing.smoke.command` so the next run is deterministic instead of
re-deriving. Recommend it; do not edit the profile yourself.

---
name: test-bar-gate
description: >-
  Pre-reviewer automated quality gate — runs lint, type-check, unit tests, and a local smoke check (does the app actually come up?) after `coding`/`testing` finish and before the reviewer fan-out. The smoke slot runs by default for runnable .NET and Python projects, deriving the start command when the profile doesn't declare one. Stack-aware via `solution-profile.yaml: quality_gates.test_bar`. On failure, returns to the author with a structured error report (no reviewer cost wasted on broken patches). Loaded by `dev-lead` between Stage 7 (Testing) and Stage 9 (Review).
applies_to: all
---

# Test-Bar Gate

A deterministic, pre-reviewer quality gate. Runs cheap, fast checks (lint → type-check → unit-tests → local smoke) so that expensive reviewer agents are never spent on a patch that does not even build, pass its own tests, or start.

## When this skill fires

Loaded by the `dev-lead` supervisor in this exact slot:

```
Stage 7 (Testing) emits  ──►  TESTS COMPLETE
                              │
                              ▼
                    ┌─────────────────────┐
                    │  test-bar-gate      │  ◄── this skill
                    └─────────────────────┘
                              │
              pass            │            fail
        ┌─────────────────────┴───────────────────────┐
        ▼                                             ▼
Stage 9 reviewer fan-out                Return to `coding` or `testing`
(architecture / security /              with structured failure report.
clean-code / test-quality /             One corrective retry allowed;
iac reviews)                            second failure → halt + ask user.
```

The gate **never** runs before `TESTS COMPLETE` — we want the unit-test layer (when applicable) to exist before grading it.

## What runs

Checks run **in this order**, **fail-fast on the first non-zero exit code**:

1. **lint** {E} formatting / style / lint rules
2. **typecheck** {E} static type or compile check
3. **unit_test** {E} unit tests only (no integration, no e2e {E} those belong to a later gate)
4. **integration_test** {E} *opt-in*, off by default (slow, usually needs containers / secrets)
5. **coverage** {E} *opt-in*; the command must carry its own threshold and exit non-zero below it
6. **mutation** {E} *opt-in*; same contract as coverage
7. **smoke** {E} — start the app and confirm it comes up. **Runs by default for .NET and Python**: uses `testing.smoke.command` when set, otherwise derives the entry point (see [`startup-discovery.md`](references/startup-discovery.md)). Skips only as `not_applicable` (nothing to start) or `undetermined` (couldn't work out how), both stated in the result.

A check runs when it is **enabled** *and* **resolves to a command**. The first three are
enabled by default and fall back to the per-stack palette; the rest run only when the
profile gives them an explicit command. Set `quality_gates.test_bar.enabled: false` to
skip the whole gate.

A missing toolchain is reported through the normal contract {E} exit code `127`, reason
`command_not_found` {E} not as a crash. On a fresh machine that is the most likely
failure, and `dev-lead` needs it parseable.

Fail-fast is the default because a lint/format failure usually means a typecheck or test run will produce noisy, derivative errors that drown the real signal. Adopters may set `quality_gates.test_bar.fail_fast: false` in `solution-profile.yaml` to run all three regardless and aggregate failures (useful in CI dashboards, rarely useful for the agent loop).

### The smoke slot

Unit tests prove the units. They do not prove the host boots — a bad DI registration, a missing connection string, a broken `host.json`, or an unresolvable startup dependency all pass the first three checks and fail the moment anyone runs the thing. The smoke slot closes that gap for the cost of one process start.

**For a runnable .NET or Python project this slot runs — it is not opt-in.** Building is not evidence that the thing starts, and "compiles, ships, doesn't boot" is precisely the failure the earlier checks cannot see. Configure it explicitly when you can, because explicit is cheaper and deterministic:

```yaml
testing:
  smoke:
    command: ["func", "start"]                          # or ["dotnet", "run", "--project", "src/Api"]
    url: "http://localhost:7071/api/health"
    timeout_s: 60
```

Procedure:

1. **Resolve the command.** `testing.smoke.command` when set. Otherwise the runner emits `outcome=skipped, reason=needs_discovery` and stops there — a script cannot inspect a repo to work out how it starts, so resolving the entry point is the *agent's* job: **derive** it, and where derivation is inconclusive **research** it, per [`startup-discovery.md`](references/startup-discovery.md). Then re-invoke the runner with what you found:

   ```bash
   ./run-gate.sh --smoke-command "dotnet run --project src/Api" --smoke-url "http://localhost:5000/health"
   ```
   ```powershell
   ./run-gate.ps1 -SmokeCommand 'uvicorn app.main:app' -SmokeUrl 'http://localhost:8000/'
   ```

   The CLI overrides exist so the start/poll/stop logic has exactly one implementation — never hand-roll the process handling around the gate.
2. The runner starts the command as a **background** process from repo root.
3. It polls the URL every 2s until it returns any HTTP status < 500, or `timeout_s` elapses. For an entry point with no HTTP surface, instead confirm the process is still alive after a few seconds and did not exit non-zero.
4. **Always** stop the process — on success, on timeout, and on any error. A leaked listener breaks the next run by holding the port. Stop it by PID; never by process name.
5. Outcome: `success` if it answered (or stayed up) in time; `failure` otherwise, with the last ~20 lines of the process's combined stdout/stderr as `stderr_tail` (a startup crash prints its stack there, and it is the only diagnostic the slot produces). Report the command and URL you used and where they came from — profile, derived, or researched.

A timeout is a **failure**, not a skip. "It did not come up within 60s" is exactly the signal the slot exists to give.

**Three distinct skip reasons, never collapsed into one.** The old behaviour — empty command means silently skip — made a run that never started the app read exactly like a run that started it fine, which is the reporting failure this gate exists to prevent:

| `reason` | Means | Is it a pass? |
|---|---|---|
| `needs_discovery` | The runner had no command. **Not a result** — resolve the entry point and re-invoke with `--smoke-command` / `--smoke-url`, then record one of the two below or a real success/failure. | No — the gate is not finished |
| `not_applicable` | There is genuinely nothing to start (class library, no entry point, docs/IaC-only diff). Detected, not assumed. | Yes — a stated pass |
| `undetermined` | There *is* something to start and neither the profile, the repo, nor research revealed how. | Yes, but reported as a gap, with what was inspected and a recommendation to set `testing.smoke.command` |

The original objection to defaults still holds and is why this is *discovery*, not guessing: a wrong command burns the full timeout and reports a startup failure that is really a configuration failure. Everything in `startup-discovery.md` reads something the project already declares, and stops at `undetermined` rather than inventing a plausible command.

Scope boundary: this slot answers *"does it come up?"* — one process, one health probe. It is not integration testing. If the app cannot start without a database, a queue, and three collaborators, that is `e2e-testing` with a compose file, not this gate.

For a web UI, a passing smoke check is a weak claim: an HTTP 200 says the server answered, not that the page renders. When the slot passes but the UI is suspect, that is the cue to escalate to `webapp-testing` and drive a real browser (console errors, failed requests, accessibility tree). The gate deliberately stays a plain HTTP poll — deterministic, no browser download on the critical path — and hands the harder question to the agent that owns it.

## Stack detection

The stack only decides which **default** commands apply. A check with an explicit
`command` in the profile needs no stack at all.

1. **Explicit stacks:** `quality_gates.test_bar.stacks` — a list. Every entry runs the full check sequence, so a polyglot repo can gate more than one stack in a single pass.
2. **Primary language:** when `stacks` is empty, `tech_stack.primary_languages[0]` is matched (case-insensitive) against the keys in `references/commands.yaml` (`csharp`, `python`, `typescript`, `go`, `bicep`, `terraform`). The entry may be a plain string or a `{ name: ... }` map.
3. **Tool hints:** if the language is not a palette key, `tech_stack.lint_format_tools` and `build_tools` are searched for a recognisable tool (`eslint`/`tsc` → `typescript`, `ruff`/`mypy`/`pyright` → `python`, `gofmt` → `go`, `dotnet` → `csharp`).
4. **No match and no explicit commands:** emit `outcome=skipped, reason=no_stack_match` and pass through. The dev-lead should warn the user that the gate is silent for this repo.

The palette's Python `typecheck` default is `pyright`. A project that uses `mypy` sets
`typecheck.command` explicitly — the gate does not guess between type checkers.

## Default command palette

See `references/commands.yaml`. The defaults assume:

- Commands are run from repo root.
- Tooling is already installed (the gate does not bootstrap toolchains — that is the responsibility of the dev container or `azure-prepare`).
- For IaC stacks (`bicep`, `terraform`) the unit-test slot is a no-op (`echo no-unit-tests`) because those stacks do not have a unit-test layer at this gate. Policy/conftest checks belong to a later gate.

## Override mechanism

Each check has its own block under `quality_gates.test_bar`, matching the shape in the
solution-profile template:

```yaml
quality_gates:
  test_bar:
    enabled: true
    fail_fast: true
    lint:
      command: ["pnpm", "lint"]     # list, or the string "pnpm lint"
    typecheck:
      command: ["pnpm", "typecheck"]
    unit_test:
      command: ["pnpm", "test", "--", "--run"]
    integration_test:
      command: ["pnpm", "test:integration"]
      enabled: true                 # opt-in checks need this
```

Rules:

- An empty or absent `command` falls back to the per-stack palette — but only for
  `lint`, `typecheck`, and `unit_test`. The other three have no defaults and stay silent
  until given a command.
- `enabled: false` skips a check outright. Prefer it over a no-op command, and note the
  reason in the PR.
- `enabled` and `command` are independent: a check needs both to run.

## Output contract

### On success

Emit one event per passing check and a final summary event:

```json
{ "event_type": "gate_check", "check": "lint",      "outcome": "success", "command": "ruff check .",   "duration_ms": 812 }
{ "event_type": "gate_check", "check": "typecheck", "outcome": "success", "command": "pyright .",       "duration_ms": 4310 }
{ "event_type": "gate_check", "check": "unit_test", "outcome": "success", "command": "pytest -q ...",   "duration_ms": 12044 }
{ "event_type": "gate_check", "check": "summary",   "outcome": "success", "stack": "python" }
```

The script exits `0`. The dev-lead proceeds to the reviewer fan-out.

### On failure

Two artefacts are produced:

1. **Structured event** — one line written to the event log:

   ```json
   {
     "event_type": "gate_check",
     "check": "typecheck",
     "outcome": "fail",
     "stack": "python",
     "command": "pyright .",
     "exit_code": 1,
     "stderr_tail": "src/foo.py:42 - error: \"None\" is not iterable\n... (truncated)"
   }
   ```

   Events are appended to `$env:COPILOT_EVENT_LOG` if set, otherwise stdout. The schema matches the global event-log convention (see `event-logging` skill if present).

2. **Markdown failure report** — printed to stdout for the dev-lead to relay. The exact template is in `references/failure-report-format.md`.

The script exits `1`.

## Retry policy

The dev-lead may invoke `coding` (for failures attributable to source) or `testing` (for failures attributable to the test layer) **once** with the structured failure report attached. If the gate fails a second time on the same task, the dev-lead **halts** and asks the user how to proceed — do not loop indefinitely on a gate that cannot be cleared.

Choose between `coding` and `testing` like this:

| Failed check | Author to re-engage |
|--------------|---------------------|
| lint         | the author whose patch introduced the violation (usually `coding`; `testing` if only test files changed) |
| typecheck    | `coding` |
| unit_test    | `coding` if a test exposed a real defect; `testing` if the test itself is wrong |
| integration_test | `coding` first — an integration failure is usually a wiring defect, not a test defect |
| coverage / mutation | `testing` — both measure the test layer |
| smoke        | `coding` — a host that will not boot is a source defect. `infrastructure` only when the failure is a missing local setting / connection string it owns. |

When in doubt, pick `coding` — a failing test on `main` blocks the reviewer fan-out either way.

## Citations

- `references/stream-a-papers.md` §13.3 — *Agentless test execution* (cheap, deterministic gates outperform LLM self-grading on short-loop quality signals).
- `references/stream-e-blogs.md` §17 — Cognition's autofix loop (one corrective retry, then escalate).
- `references/stream-e-blogs.md` §22 — Stripe's deterministic graders (lint/type/test as the floor, reviewers as the ceiling).

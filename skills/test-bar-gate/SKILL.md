---
name: test-bar-gate
description: >-
  Pre-reviewer automated quality gate — runs lint, type-check, and unit tests after `coding`/`testing` finish and before the reviewer fan-out. Stack-aware via `solution-profile.yaml: quality_gates.test_bar`. On failure, returns to the author with a structured error report (no reviewer cost wasted on broken patches). Loaded by `dev-lead` between Stage 4 (Testing) and Stage 5 (Review).
---

# Test-Bar Gate

A deterministic, pre-reviewer quality gate. Runs cheap, fast checks (lint → type-check → unit-tests) so that expensive reviewer agents are never spent on a patch that does not even build or pass its own tests.

## When this skill fires

Loaded by the `dev-lead` supervisor in this exact slot:

```
Stage 4 (Testing) emits  ──►  TESTS COMPLETE
                              │
                              ▼
                    ┌─────────────────────┐
                    │  test-bar-gate      │  ◄── this skill
                    └─────────────────────┘
                              │
              pass            │            fail
        ┌─────────────────────┴───────────────────────┐
        ▼                                             ▼
Stage 5 reviewer fan-out                Return to `coding` or `testing`
(architecture / security /              with structured failure report.
clean-code / test-quality /             One corrective retry allowed;
iac reviews)                            second failure → halt + ask user.
```

The gate **never** runs before `TESTS COMPLETE` — we want the unit-test layer (when applicable) to exist before grading it.

## What runs

Three checks, **in order**, **fail-fast on the first non-zero exit code**:

1. **lint** — formatting / style / lint rules
2. **typecheck** — static type or compile check
3. **test** — unit tests only (no integration, no e2e — those belong to a later gate)

Fail-fast is the default because a lint/format failure usually means a typecheck or test run will produce noisy, derivative errors that drown the real signal. Adopters may set `quality_gates.test_bar.fail_fast: false` in `solution-profile.yaml` to run all three regardless and aggregate failures (useful in CI dashboards, rarely useful for the agent loop).

## Stack detection

Resolved in this order — first hit wins:

1. **Explicit override:** `solution-profile.yaml: quality_gates.test_bar.commands` (a map shaped like `references/commands.yaml`). When present, the defaults are ignored entirely — the project owns the contract.
2. **Primary language match:** `tech_stack.primary_languages[0]` is matched (case-insensitive) against the keys in `references/commands.yaml` (`csharp`, `python`, `typescript`, `go`, `bicep`, `terraform`).
3. **Tool hints:** if no language match, look at `tech_stack.lint_format_tools` and `build_tools` to pick the closest stack (e.g. `eslint` → `typescript`, `ruff` → `python`).
4. **No match:** emit a `gate_check` event with `outcome=skipped, reason=no_stack_match` and pass through. The dev-lead should warn the user that the gate is silent for this repo.

For Python, the default `typecheck` command is `pyright`; if `pyright` is not present in `tech_stack.lint_format_tools` but `mypy` is, swap to `["mypy", "."]`.

## Default command palette

See `references/commands.yaml`. The defaults assume:

- Commands are run from repo root.
- Tooling is already installed (the gate does not bootstrap toolchains — that is the responsibility of the dev container or `azure-prepare`).
- For IaC stacks (`bicep`, `terraform`) the unit-test slot is a no-op (`echo no-unit-tests`) because those stacks do not have a unit-test layer at this gate. Policy/conftest checks belong to a later gate.

## Override mechanism

Adopters override per-stack defaults by placing a `commands:` block under `quality_gates.test_bar` in `solution-profile.yaml`:

```yaml
quality_gates:
  test_bar:
    fail_fast: true
    commands:
      lint: ["pnpm", "lint"]
      typecheck: ["pnpm", "typecheck"]
      test: ["pnpm", "test", "--", "--run"]
```

When `commands:` is present, **every** key it contains overrides the default. A missing key falls back to the default for the detected stack. To explicitly skip a check, set its command to `["true"]` (POSIX) or `["cmd", "/c", "exit", "0"]` (Windows) — but document why.

## Output contract

### On success

Emit one event per passing check and a final summary event:

```json
{ "event_type": "gate_check", "check": "lint",      "outcome": "success", "command": "ruff check .",   "duration_ms": 812 }
{ "event_type": "gate_check", "check": "typecheck", "outcome": "success", "command": "pyright .",       "duration_ms": 4310 }
{ "event_type": "gate_check", "check": "test",      "outcome": "success", "command": "pytest -q ...",   "duration_ms": 12044 }
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
| test         | `coding` if a test exposed a real defect; `testing` if the test itself is wrong |

When in doubt, pick `coding` — a failing test on `main` blocks the reviewer fan-out either way.

## Citations

- `references/stream-a-papers.md` §13.3 — *Agentless test execution* (cheap, deterministic gates outperform LLM self-grading on short-loop quality signals).
- `references/stream-e-blogs.md` §17 — Cognition's autofix loop (one corrective retry, then escalate).
- `references/stream-e-blogs.md` §22 — Stripe's deterministic graders (lint/type/test as the floor, reviewers as the ceiling).

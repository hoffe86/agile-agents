---
name: test-bar-gate
description: >-
  Deterministic pre-reviewer gate: solution-declared lint, type-check, tests and
  local smoke after implementation and before review. No language command palette.
  Missing required commands or unresolved startup are configuration gaps, not
  successful skips. Preserves failure evidence, bounded smoke polling and process
  cleanup. Loaded by dev-lead between Stage 6 (Implement) and Stage 8 (Review).
metadata:
  applies_to: all
---

# Test-Bar Gate

Run cheap deterministic checks before spending reviewer effort. The supervisor
invokes the runner over the **combined** diff after all Stage 6 tasks are done,
and again after corrective changes before re-review. Per-task passes do not
prove combined behavior. Attach fresh results and content identity; re-entry
never resets the supervisor's retry budget.

## Profile and command contract

Resolve `.github/solution-profile.yaml`. Explicit
`--profile` / `-ProfilePath` never falls back. Missing, unreadable, malformed,
empty or non-mapping profiles exit **2 (configuration error)**.

Use the existing schema, **`quality_gates.test_bar.<check>.command`**:

1. `lint`
2. `typecheck`
3. `unit_test`
4. `integration_test`
5. `coverage`
6. `mutation`
7. Smoke from `testing.smoke`, after the above.

The first three checks remain enabled by default; the other three are opt-in
via `enabled: true`. Every enabled check requires a solution command. Coverage
and mutation commands must enforce their own floor and exit nonzero below it.
No language, framework, alias or tool hint supplies a command.

Commands execute **once**, from repo root. An argv list preserves spaces inside
arguments; a plain string uses whitespace splitting, not shell
parsing. List items must be single-line strings (empty argument values are
preserved). For pipes, redirects or complex quoting, declare an existing solution
script as the command. No implicit shell evaluation.

Polyglot solutions compose their own check scripts. No palette or stack selector.

`enabled: false` is a visible `skipped, reason=disabled_by_profile` event.
Unset opt-in checks report `disabled_by_default`. The master
`quality_gates.test_bar.enabled: false` skips the whole gate visibly.
An enabled check with no command emits `fail, reason=configuration_gap`, names
the missing profile path and exits **2**. It cannot reach a success summary.

`fail_fast: true` remains the default. `false` aggregates failures, including
configuration gaps; any gap keeps exit 2 even if another check exits nonzero.
Missing executables emit `fail`, `exit_code=127`, `reason=command_not_found`.
The runner exits **1** for executed-check failures; actual child exit codes and
the last 30 stderr lines remain in evidence.

## Smoke lifecycle

A runnable application must start; a build does not prove host configuration,
dependency wiring or startup work. Use `testing.smoke.command`, `url`,
`timeout_s` (positive integer, default 60). CLI command/URL overrides retain
their existing names: `--smoke-command` / `--smoke-url` in Bash and
`-SmokeCommand` / `-SmokeUrl` in PowerShell. Commands come from actual solution
evidence; see [startup-discovery.md](references/startup-discovery.md).

1. Resolve the declared start command and health URL. Missing either emits
   `fail, reason=needs_discovery` and exits **2**, not success.
2. Start the process at repo root, capturing startup stdout/stderr.
3. Poll the HTTP(S) URL within the fixed `timeout_s` deadline. An HTTP response
   from 100 through 499 proves reachability, **not application correctness**.
   The process must still be alive. Bound requests and polling waits.
4. Always stop the owned process tree on success, timeout or error; never kill
   by process name. The command must remain attached, not daemonize into a
   separate session. Do not leave a listener or claim cleanup without evidence.

PowerShell establishes ownership before launch (a Unix process group or Windows
kill-on-close job), with a separate 5s setup bound. Launcher exit does not release
descendants. Failure-output draining is capped at 2s and reports available partial
output rather than requiring EOF.
5. Timeout/early exit fails with startup output, reason and the child exit code
   when available. For non-HTTP entry points, use a solution-owned readiness adapter;
   absent one, report undetermined rather than pretend "still alive" is tested.

The script cannot infer whether a repository has an application. A caller that
has inspected it may supply a status **and nonblank evidence**:

| CLI status | Result | Verified? |
|---|---|---|
| `--smoke-status not_applicable --smoke-detail "<evidence>"` | Visible skip; exit 0 if all applicable checks pass | Nothing to start; not a startup pass |
| `--smoke-status undetermined --smoke-detail "<inspected sources/gap>"` | Failure; exit 2 | No; blocks verified Done |
| No status and incomplete setup | `needs_discovery`; exit 2 | No; resolve and re-run |

PowerShell equivalents: `-SmokeStatus` and `-SmokeDetail`. `not_applicable`
conflicting with a configured command/URL is a configuration gap, not an
escape hatch. All checks disabled plus smoke not applicable yields a skipped
summary (`no_checks_enabled`), never an all-checks-passed claim.

Smoke is one process and one health probe, not integration/E2E verification.
A UI may return 200 and render incorrectly. Use actually available, applicable
solution browser capabilities for diagnosis; otherwise report that limitation.
The gate never downloads a browser or provisions dependencies.

Runner prerequisites remain installed tooling, not bootstrap actions: Bash uses
mikefarah `yq` v4 and `curl`; PowerShell uses `powershell-yaml`. PowerShell smoke
requires 7.2+ (.NET 6+) for explicit Unix signal cleanup; older hosts report a
configuration gap before starting anything. SIGINT/SIGTERM clean up owned
processes and exit nonzero; an uncatchable host kill cannot guarantee cleanup.

## Output and retry contract

Passing checks emit `gate_check` events with `check`, `outcome=success`,
`command`, `duration_ms`; a final success summary appears only after all
applicable checks pass.

Failing checks emit `outcome=fail`, `exit_code`, `command`, `stderr_tail` and a
reason when available. Configuration failures name the missing setting in
`detail`. Events append to `COPILOT_EVENT_LOG` when set, otherwise stdout.
The supervisor owns run-level events; the runner only emits gate-check evidence.
Markdown failures follow [failure-report-format.md](references/failure-report-format.md).

Exit codes: **0** applicable checks passed or explicit skips; **1** execution
failure; **2** configuration gap/unverified. Exit 2 stops for configuration
repair, not a source-code retry. Never reinterpret it as unsupported-stack success.

For actual execution failures, `dev-lead` may re-engage the author **up to three
times**, with unchanged failure evidence and what the prior attempt missed.
Halt on the fourth failure, or earlier when a round reduces no failing checks.
Do not dispatch reviewers on a failed or unverified required gate.

| Failure belongs to | Author |
|---|---|
| Application lint/type/test/coverage/mutation or host startup | `coding` |
| IaC, pipelines or owned local infrastructure prerequisites | `infrastructure` |
| Missing command/access or unresolved startup | Stop for solution configuration |

Application tests remain `coding`'s responsibility. A retry changing an
assertion must state what it previously claimed and why that claim was invalid;
never weaken tests to hide a production defect. Preserve that justification
for `test-reviewer`.

## Command provenance

Populate enabled checks only with verified existing CI/script commands; capture
source, working directory and prerequisites in solution guidance. Bootstrap may
propose evidenced values for confirmation, never guess from language names.
Disable only genuinely inapplicable checks explicitly, with a reason.

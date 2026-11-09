---
name: testing-practices
description: >-
  Technology-neutral author-owned test coverage, deterministic fixtures, E2E
  diagnosis and assertion integrity. Pair with development-practices for code
  changes; use alone for test repair. Not independent review or the test-bar gate.
metadata:
  applies_to: all
---

# Testing practices

The current author owns implementation and its tests. Do not self-delegate or
launch another testing pipeline; reviewers use guidance as reference only.
The invoking `coding` author may fix production logic within scope; never weaken
assertions to pass it.

## 1. Craft bias

- **Test behaviour, not implementation.** A test that breaks on a rename but not
  on a bug is a liability. Assert on observable outcomes and contracts.
- **Fewest tests that would actually catch the bug.** Coverage of the *changed
  behaviour* — happy path, the edge that bites, the negative path — beats a
  percentage. Don't generate one test per method for the metric.
- **Prefer real over mocked.** Mock only what you cannot control (network,
  clock, external service, randomness). Over-mocking tests the mock, not the
  code.
- **Deterministic.** Repair sleeps, ordering dependence, shared mutable state and
  uncontrolled live network; do not delete failing tests to manufacture green.
- **Never simplify away:** a failing test that reveals a real defect (report it,
  never weaken the assertion), validation / authz / error-path coverage, or an
  explicitly requested case.

## 2. The boundary that does not move

**Never delete, skip, loosen or re-baseline a test to get green.** That is a
finding, not a fix.

Treat a red test as evidence about production code until proven otherwise:

- **The test is right and the code is wrong** → fix the code. Say so in the
  hand-off: which behaviour was wrong, which test caught it.
- **The test is wrong** (asserts an implementation detail, encodes a stale
  contract, is non-deterministic) → fix the test, and **justify the change in the
  hand-off** naming what the old assertion claimed and why that claim was
  invalid.
- **You can't tell** → stop and surface it. Don't pick whichever edit makes the
  bar go green.

Never regenerate snapshots or fixtures wholesale without an explicit human ask —
a regenerated snapshot asserts nothing about whether the new output is correct.

## 3. Framework routing

Use `read-repo-context` discovery: match actual available descriptions/capabilities
from local skills and installed external plugins to the task, paths, language and
test framework/version. Detect existing test manifests, configuration, CI commands
and test conventions before proposing gaps. No historical skill names or mandatory
companion catalog. Distinguish absent from ungranted.

Without matching optional depth, use repo conventions and authoritative framework
documentation; do not assume any scaffolding skill is available or applicable. Report the
fallback in the hand-off. All general testing rules still apply.
Missing tooling is a reported gap, not permission to install dependencies.
Run native repo commands for build, targeted tests, full suite, lint and format.
Use existing coverage tooling; when absent, report **not measured**, never an
invented percentage. Justify every existing-test change as required by §2.
In `IMPLEMENTATION COMPLETE`, `Existing tests modified` names what the old
assertion claimed and why it was invalid. Do not re-enter this workflow as a
fallback or start a separate agent chain.

Honour `team_communication.code_language` for test names and BDD scenarios, and
`tech_stack.test_discipline` for whether tests are written before or after the
production code.

## 4. Web UI and end-to-end

Cover changed user journeys crossing UI/API/service boundaries after unit tests.
There is no harness default framework. Match actually available guidance to the
declared framework/version, task and paths; otherwise use repo conventions and
authoritative docs and report the fallback. Authoring and interactive diagnosis
are separate capabilities.

Honour **all five** `testing.e2e` fields:

| Field | Contract |
|---|---|
| `framework` | Use the selected suite. `none` is explicit disablement. |
| `base_url` | Runner target, never a hard-coded spec URL. |
| `headless` | Committed launch default; headed debugging stays a local override. |
| `parallelism` | Committed worker/shard count. |
| `flake_retries` | Committed retry budget, not permission to mask flakes. |

If `framework=none`, report **E2E coverage explicitly disabled by profile; no
browser-level verification; user-visible regression risk remains**. Do not
silently skip. A missing framework or empty `base_url` with an enabled framework
is a **configuration gap: stop and ask**. For other empty options retain native
defaults and name them; do not invent values.

Inspect the real page, accessibility tree, console errors and failed requests
before choosing selectors or assertions; HTTP 200 is not UI verification.
Assert critical journeys and negative paths using stable semantic selectors and
bounded readiness waits, not sleeps. Use isolated, disposable fixtures; never
share mutable state or a dev/production database. Reset only owned resources.
Missing fixture setup is a gap, not a package-install instruction.

Capture trace + screenshot on failure and the solution's CI-compatible report;
retain evidence under its policy, excluding secrets and PII. Close the browser
and clean up owned fixtures/processes even on failure. Diagnose unexplained
failures interactively, then encode the finding in durable suite assertions.
Run locally and confirm green twice in a row before hand-off.

Pipeline implementation belongs to infrastructure. Pass the existing commands,
after-unit-test ordering, profile options and evidence/retention requirements;
do not write provider pipeline recipes here.

## 5. Hard rules

- **Cover every behaviour you changed.** Each item you list as
  added/modified behaviour needs at least one test asserting it. Aim for 100%
  coverage of the lines you added or modified this session; don't chase coverage
  on unrelated legacy code. Honour `tech_stack.coverage_threshold` where the
  profile sets one.
- **Edge cases are mandatory.** Null handling, empty collections, boundary
  values, and error paths — these are explicit Pre-PR review items, not extras.
- **No regressions.** Existing tests must still pass. If a change requires
  modifying an existing test, §2 applies.
- **Test through public APIs.** Don't widen visibility to make something
  testable; avoid test-only access grants unless the project already uses them. If
  there is genuinely no alternative, make the smallest visibility change and
  flag it explicitly in the hand-off — a type that is hard to test is usually a
  design signal worth reporting.
- **One behaviour per test.** No conditionals or loops inside a test.
- **No flakiness.** Unit tests isolate external I/O. Integration tests use
  controlled, disposable resources, bounded waits and reliable cleanup; never
  shared services or uncontrolled live network.
- **Security in fixtures.** No real secrets, tokens, connection strings, or PII
  in test data (`compliance_security.secret_scanning_required`). Use ephemeral or
  generated values, or a sealed test vault.
- **It must *be* green, not "should be" green.** Run the suite, lint and format
  locally before handing off.

## 6. When a test won't go green

- **Tight feedback loop.** If a test still fails after a fix, try a **different
  approach** — don't repeat the same strategy. After 2–3 failed attempts, step
  back and rethink the root cause.
- **Persist until resolved.** Don't hand back "mostly green" — finish it, or
  stop explicitly and surface why.
- **Escalate rather than mutate.** If passing would require a production change
  that exceeds the task's scope — a new dependency, a contract change, a design
  decision — stop and report it instead of making the change quietly. Inside the
  task's scope, fixing the production code is exactly what you are for (§2).

## 7. Relationship to the automated gate

After author verification, the orchestrator runs `test-bar-gate` over the combined
diff (lint → typecheck → unit-test → smoke). Author tests must assert changed
behavior; neither check replaces the other.

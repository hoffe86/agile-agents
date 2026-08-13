---
name: testing-practices
description: >-
  The verification half of the build-and-verify craft — test-behaviour-not-
  implementation bias, coverage of the changed behaviour, mocking discipline,
  determinism rules, framework routing, interactive browser debugging, and the
  never-weaken-a-test boundary. Technology-neutral: detects the framework the
  repo already uses and routes to whichever language testing skill the project
  installed. Loaded by the `coding` agent on every task that changes testable
  code, alongside `development-practices` (its implementation half). USE FOR:
  covering new or changed behaviour, repairing failing tests, adding edge-case
  and negative-path tests, setting up fixtures, diagnosing a failure the output
  doesn't explain. DO NOT USE FOR: reviewing someone else's test diff (that is
  the `test-reviewer` agent), IaC tests like Terratest / Pester (those belong to
  the infrastructure agent), or the pre-reviewer automated gate (that is
  `test-bar-gate`).
applies_to: all
---

# Testing practices

The craft bar for proving a change works. Paired with
**`development-practices`** — one agent loads both, because a change is not
finished when it compiles, it is finished when something demonstrates it
behaves.

An unreliable test is worse than no test: it costs attention every run and
teaches the team to ignore red.

`engineering-standards` applies to test code too (tests are code) and is **not
restated here**. What follows are the testing-specific deltas.

## 1. Craft bias

- **Test behaviour, not implementation.** A test that breaks on a rename but not
  on a bug is a liability. Assert on observable outcomes and contracts.
- **Fewest tests that would actually catch the bug.** Coverage of the *changed
  behaviour* — happy path, the edge that bites, the negative path — beats a
  percentage. Don't generate one test per method for the metric.
- **Prefer real over mocked.** Mock only what you cannot control (network,
  clock, external service, randomness). Over-mocking tests the mock, not the
  code.
- **Deterministic or delete it.** No sleeps, no ordering dependence, no shared
  mutable state, no live network. A test you have to re-run is broken.
- **Never simplify away:** a failing test that reveals a real defect (report it,
  never weaken the assertion), validation / authz / error-path coverage, or an
  explicitly requested case.

## 2. The boundary that does not move

**Never delete, skip, loosen or re-baseline a test to get green.** That is a
finding, not a fix.

This is the one rule that survives merging implementation and testing into a
single agent. When the same agent owns the code and its tests, the cheapest path
to green is always to change the assertion — so treat a red test as evidence
about the production code until you have proved otherwise, and record the
verdict:

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

Route by the repo's actual stack (`solution-profile.yaml:
tech_stack.primary_languages` + `test_frameworks`), not by assumption. **Check
availability first, then language** — a language skill is a bonus, never a
precondition:

- **A skill for the language is available** → invoke it (currently
  `csharp-testing`, which itself routes to `csharp-xunit`, `csharp-nunit`,
  `csharp-mstest` or `csharp-tunit` when those separately installed plugin
  skills are present; `python-testing` then `pytest-coverage` for coverage
  analysis — all ship in companion plugins and may not be installed). Do not
  assume the set is fixed.
- **No skill for the language is available** (TypeScript / Go / Java / Rust /
  … , or the expected skill isn't installed) → detect the framework the repo
  already uses (test manifest, config file, CI workflow, existing test files) and
  follow its conventions. `polyglot-test-agent` is the fallback for
  cross-language test patterns. Everything else in this skill is
  language-neutral and still applies. **Say in the hand-off that you worked
  without a language skill.**

Honour `team_communication.code_language` for test names and BDD scenarios, and
`tech_stack.test_discipline` for whether tests are written before or after the
production code.

## 4. Web UI and end-to-end

Three skills, three different questions — all available, pick by deliverable:

- `e2e-testing` — author and run a durable Playwright / Selenium **suite** that
  ships with the repo and runs in CI. Use it when the deliverable is a test file.
- `playwright-generate-test` (vendored) — turn a described scenario into a
  Playwright test by driving the `playwright/*` MCP server through the flow
  first, so the generated selectors and assertions come from the real page
  rather than from a guess. Use it inside `e2e-testing`'s workflow when you have
  a scenario but not yet a test; `e2e-testing` still owns suite structure,
  fixtures and CI wiring.
- `webapp-testing` — drive a browser **interactively** through the
  `playwright/*` MCP tools: open the page, read the accessibility tree, inspect
  console errors and failed network requests, screenshot. Use it to *find out
  what is actually wrong* — a 200 response with a white screen, a broken
  hydration, a CSP violation — none of which an HTTP status check can see.
  Findings become assertions in the suite; the interactive session itself is not
  the deliverable.

Reach for interactive driving when a test fails for a reason the failure output
does not explain, or when the smoke slot reports the app up but the UI does not
work. **Always close the browser when you are done.**

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
  testable; avoid `InternalsVisibleTo` unless the project already uses it. If
  there is genuinely no alternative, make the smallest visibility change and
  flag it explicitly in the hand-off — a type that is hard to test is usually a
  design signal worth reporting.
- **One behaviour per test.** No conditionals or loops inside a test.
- **No flakiness.** Deterministic, parallel-safe, free of real network and disk
  I/O.
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

`test-bar-gate` (lint → typecheck → unit-test → smoke) runs **after** you, as a
deterministic pre-reviewer gate the orchestrator invokes. It is not a substitute
for this skill and this skill is not a substitute for it: the gate proves the
repo's declared commands pass over the combined diff; you prove the changed
behaviour is actually asserted. If you can predict a gate failure, fix it now —
a gate failure costs a full corrective round.

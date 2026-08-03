---
name: e2e-testing
description: >-
  End-to-end testing playbook for full-stack work — Playwright (TypeScript/Python) or Selenium (Python) backend selected via `solution-profile.yaml: testing.e2e.framework` (or `none` to skip). Loaded by `testing` agent after unit tests pass when the change includes a UI surface or HTTP/API surface that warrants browser-level verification.
applies_to: all
---

# E2E Testing Playbook

End-to-end (E2E) tests verify a user journey through the *real* stack — browser, server, dependencies — and catch failure modes that unit and integration tests miss. Without them, agents (and humans) routinely mark features "complete" without ever exercising the full path the user takes (Anthropic — see `stream-e-blogs.md` §7). With them, you get the same confidence Stripe gets from running browser automations as a release gate (`stream-e-blogs.md` §22).

## Backend selection

The active backend is chosen in `solution-profile.yaml`:

```yaml
testing:
  e2e:
    framework: playwright   # playwright | selenium | none
```

| Value        | When to pick it                                                                                |
|--------------|------------------------------------------------------------------------------------------------|
| `playwright` | **Default for web apps.** Modern, fast, multi-browser, supports TS/Python/Java/.NET. First choice unless you have a hard reason against it. |
| `selenium`   | Legacy stacks with existing Selenium suites, Python-heavy ecosystems already on `pytest-selenium`, or enterprise apps that must still target IE/Edge-Legacy / ATDD frameworks like Robot. |
| `none`       | E2E explicitly disabled (e.g., pure CLI tool, library-only repo). Skill exits with a single trade-off note — see *Stop conditions* below. |

For backend specifics, load:

- `references/playwright-playbook.md`
- `references/selenium-playbook.md`
- `references/e2e-anti-patterns.md` (always)

## When to use this skill

Run E2E coverage when the change touches **any** of:

- A user-facing UI (web page, SPA route, form, modal).
- An HTTP/API endpoint that integrates **multiple** services (DB + auth + downstream API).
- A workflow that crosses the browser↔server boundary (login → action → server effect → UI confirmation).

## When NOT to use this skill

Skip E2E (unit + integration is enough) when the change is:

- Pure backend logic with no new client-visible behaviour.
- A standalone library / SDK package.
- IaC-only (handled by `iac-best-practices` validation).
- Documentation-only.

In those cases, do not load this skill — the `testing` agent should not branch into E2E.

## Workflow

1. **Read `solution-profile.yaml`** → resolve `testing.e2e.framework`.
2. If `none` → emit trade-off note (see *Stop conditions*) and exit.
3. Load the matching playbook reference (`playwright-playbook.md` or `selenium-playbook.md`).
4. Identify the **critical user journeys** for the change — aim for 10–20 total per app, not "click everything". One spec file per journey.
5. Apply the **Page Object Model (POM)**: one POM class per major flow (`LoginPage`, `DashboardPage`, …). Tests describe intent, POMs encapsulate selectors and actions. This is the single biggest lever against flakiness and rewrite cost.
6. **Test data:** prefer ephemeral fixtures (per-test seeded data, factory functions). When backend integration is required, use **TestContainers** to spin up a disposable DB / Kafka / Redis. Never share mutable state across tests, never point E2E at a shared dev DB.
7. **Headless by default in CI**, headed locally for debugging.
8. **Always enable trace + screenshot on failure** — see anti-patterns reference.
9. Emit **JUnit XML** (`--reporter=junit` for Playwright, `--junitxml=` for pytest) so CI surfaces failures in the standard PR UI.
10. Run the suite locally once before handing off. Confirm it goes green twice in a row (flake check).

## CI integration

The framework's CI pipeline expects:

- A dedicated job (e.g., `e2e`) that runs **after** unit tests pass.
- JUnit XML uploaded as a test report.
- Trace files + failure screenshots uploaded as build artifacts (retention ≥ 7 days).
- Browser binaries cached between runs (`~/.cache/ms-playwright` for Playwright).

GitHub Actions snippets are in the per-backend playbooks.

## Stop conditions

If `testing.e2e.framework: none`, emit exactly one entry in the agent's trade-off report and exit:

> **Trade-off — E2E coverage explicitly disabled by profile.** `testing.e2e.framework=none` in `solution-profile.yaml`. No browser-level verification was performed. Risk: regressions in user-visible flows will not be caught by automated tests.

Do **not** silently skip. The whole point of the profile flag is that the disablement is recorded and visible.

## Citations

- `stream-e-blogs.md` §22 — Stripe browser E2E as release gate.
- `stream-e-blogs.md` §7 — Anthropic: without E2E, Claude marks features complete without verifying.
- Playwright best practices: https://playwright.dev/docs/best-practices
- Selenium docs: https://www.selenium.dev/documentation/

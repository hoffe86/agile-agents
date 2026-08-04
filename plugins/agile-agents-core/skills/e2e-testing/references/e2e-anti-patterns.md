# E2E Anti-Patterns

The six failure modes that turn an E2E suite from a release gate into a liability. Each entry: what it looks like, why it bites, and the one-liner fix.

## 1. Flaky waits (`sleep(2)` everywhere)

Hard sleeps either over-wait (slow suite) or under-wait (random failures on a slow CI runner). Symptom: "works locally, fails in CI 1-in-5 times".

Use the framework's auto-waiting locator API:

```ts
await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
```

```python
WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.dashboard")))
```

## 2. Test interdependence (shared mutable state)

If `test_b` only passes when `test_a` ran first, you've coupled them. Reordering, retries, or parallel runs will explode at random.

Reset state per test in a fixture:

```python
@pytest.fixture(autouse=True)
def reset_db(): truncate_all_tables(); yield
```

## 3. Slow suites (everything serial)

A 40-minute E2E run gets skipped or disabled. Parallelize at file level (Playwright does this by default; pytest needs `pytest-xdist`), and push expensive long-running flows to a nightly job, not per-PR.

```bash
pytest tests/e2e -n auto          # pytest-xdist parallel run
```

## 4. "Click everything" tests

Trying to E2E every button gives you 200 brittle tests, all slow, all flaky, none diagnostic. Pick **10–20 critical user journeys** (signup, login, primary action, payment, logout) and let unit/integration tests cover the rest.

```text
# tests/e2e/CRITICAL_JOURNEYS.md
1. Anonymous user signs up + verifies email
2. Returning user logs in + lands on dashboard
3. Authenticated user completes <primary action>
... (cap at ~20)
```

## 5. No screenshots / traces on failure

Without artifacts, a CI failure is unactionable — you can't tell whether the button moved, the API 500'd, or the test data was wrong. Always enable trace + screenshot.

```ts
use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' }
```

## 6. Hard-coded environment URLs / credentials

Tests with `https://prod.example.com` and a real password baked in cannot run against staging or a local dev stack — and leak secrets if the repo goes public. Drive everything from env vars.

```ts
baseURL: process.env.BASE_URL ?? 'http://localhost:3000'
```

# Playwright Playbook

Playwright is the default E2E backend. Multi-browser (Chromium, Firefox, WebKit), parallel by default, ships its own auto-waiting locator API that eliminates most flakiness.

Reference: https://playwright.dev/docs/best-practices

## Install

**TypeScript (recommended for web apps):**

```bash
npm i -D @playwright/test
npx playwright install --with-deps
```

**Python:**

```bash
pip install playwright pytest-playwright
playwright install --with-deps
```

## Project structure

```
tests/
  e2e/
    login.spec.ts         # one spec per user journey
    checkout.spec.ts
  pages/
    LoginPage.ts          # one POM per flow
    DashboardPage.ts
  fixtures/
    test-users.ts         # ephemeral test data factories
playwright.config.ts
```

## Sample test — TypeScript (POM)

`tests/pages/LoginPage.ts`:

```ts
import { Page, Locator, expect } from '@playwright/test';

export class LoginPage {
  readonly email: Locator;
  readonly password: Locator;
  readonly submit: Locator;

  constructor(private page: Page) {
    this.email = page.getByLabel('Email');
    this.password = page.getByLabel('Password');
    this.submit = page.getByRole('button', { name: 'Sign in' });
  }

  async goto() { await this.page.goto('/login'); }

  async loginAs(email: string, password: string) {
    await this.email.fill(email);
    await this.password.fill(password);
    await this.submit.click();
  }
}
```

`tests/e2e/login.spec.ts`:

```ts
import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/LoginPage';

test('user can log in and reach the dashboard', async ({ page }) => {
  const login = new LoginPage(page);
  await login.goto();
  await login.loginAs('alice@example.com', 'correct-horse-battery');
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await expect(page).toHaveURL(/\/dashboard$/);
});
```

## Sample test — Python (POM)

`tests/pages/login_page.py`:

```python
class LoginPage:
    def __init__(self, page):
        self.page = page
        self.email = page.get_by_label("Email")
        self.password = page.get_by_label("Password")
        self.submit = page.get_by_role("button", name="Sign in")

    def goto(self): self.page.goto("/login")

    def login_as(self, email, password):
        self.email.fill(email)
        self.password.fill(password)
        self.submit.click()
```

`tests/e2e/test_login.py`:

```python
from playwright.sync_api import expect
from tests.pages.login_page import LoginPage

def test_login_reaches_dashboard(page):
    login = LoginPage(page)
    login.goto()
    login.login_as("alice@example.com", "correct-horse-battery")
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page).to_have_url("/dashboard")
```

## `playwright.config.ts` — trace + screenshot on failure

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  reporter: [['junit', { outputFile: 'test-results/junit.xml' }], ['html']],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
```

## GitHub Actions — `.github/workflows/playwright.yml`

Mirrors the upstream template (https://playwright.dev/docs/ci-intro):

```yaml
name: Playwright E2E
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
jobs:
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: npm }
      - run: npm ci
      - name: Cache Playwright browsers
        uses: actions/cache@v4
        with:
          path: ~/.cache/ms-playwright
          key: pw-${{ runner.os }}-${{ hashFiles('package-lock.json') }}
      - run: npx playwright install --with-deps
      - run: npx playwright test
      - name: Upload JUnit results
        if: always()
        uses: actions/upload-artifact@v4
        with: { name: junit, path: test-results/junit.xml }
      - name: Upload trace + screenshots
        if: failure()
        uses: actions/upload-artifact@v4
        with: { name: playwright-trace, path: test-results/, retention-days: 7 }
```

## Tips

- Prefer **role-based locators** (`getByRole`, `getByLabel`) over CSS/XPath — they survive markup refactors.
- Use `expect(locator).toBeVisible()` etc. — they auto-retry. Never `await page.waitForTimeout(...)`.
- One browser context per test = full isolation, no cookie leakage.

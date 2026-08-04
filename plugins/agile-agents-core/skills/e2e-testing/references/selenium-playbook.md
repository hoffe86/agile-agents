# Selenium Playbook (Python)

Selenium is the fallback backend for legacy or enterprise stacks. Pick it only when there's a concrete reason; otherwise prefer Playwright.

Reference: https://www.selenium.dev/documentation/

## When Selenium over Playwright

- Existing Selenium test suite worth preserving / extending.
- Python-heavy stack already standardised on `pytest-selenium`.
- Internal enterprise apps still requiring **IE / Edge-Legacy** support.
- ATDD frameworks built on top of Selenium (e.g., **Robot Framework**, Behave + selenium webdriver).
- Hard organisational mandate (some regulated industries).

For greenfield web apps with no legacy constraint → use Playwright instead.

## Install

```bash
pip install selenium pytest-selenium webdriver-manager
```

`webdriver-manager` auto-downloads the right driver per browser, removing the "matching chromedriver to Chrome version" maintenance burden.

## Project structure

```
tests/
  e2e/
    test_login.py
  pages/
    login_page.py
    dashboard_page.py
conftest.py
pytest.ini
```

## Sample test — `pytest-selenium` + POM

`tests/pages/login_page.py`:

```python
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class LoginPage:
    URL = "/login"

    def __init__(self, driver, base_url):
        self.driver = driver
        self.base_url = base_url

    def goto(self):
        self.driver.get(self.base_url + self.URL)

    def login_as(self, email, password):
        self.driver.find_element(By.NAME, "email").send_keys(email)
        self.driver.find_element(By.NAME, "password").send_keys(password)
        self.driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.dashboard"))
        )
```

`conftest.py` — webdriver-manager pattern (cross-browser):

```python
import os
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

@pytest.fixture
def driver():
    browser = os.getenv("BROWSER", "chrome")
    if browser == "firefox":
        d = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()))
    else:
        opts = webdriver.ChromeOptions()
        if os.getenv("CI"):
            opts.add_argument("--headless=new")
        d = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
    yield d
    d.quit()

@pytest.fixture
def base_url():
    return os.getenv("BASE_URL", "http://localhost:3000")
```

`tests/e2e/test_login.py`:

```python
from tests.pages.login_page import LoginPage

def test_login_reaches_dashboard(driver, base_url):
    login = LoginPage(driver, base_url)
    login.goto()
    login.login_as("alice@example.com", "correct-horse-battery")
    assert "/dashboard" in driver.current_url
```

## GitHub Actions — `.github/workflows/selenium.yml`

```yaml
name: Selenium E2E
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
jobs:
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    strategy:
      matrix:
        browser: [chrome, firefox]
    env:
      BROWSER: ${{ matrix.browser }}
      CI: "true"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: pip }
      - run: pip install -r requirements.txt
      - name: Run Selenium suite
        run: pytest tests/e2e --junitxml=test-results/junit-${{ matrix.browser }}.xml
      - name: Upload JUnit
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: junit-${{ matrix.browser }}
          path: test-results/
```

## Tips

- **Always** use `WebDriverWait` + `expected_conditions`. Never `time.sleep()`.
- Prefer stable selectors (`data-testid`) over CSS-class chains.
- Configure failure screenshots via the `pytest-selenium` `selenium_capture_debug=always` setting or a custom `pytest_runtest_makereport` hook.
- Run headless in CI (`--headless=new` for Chrome ≥ 109).

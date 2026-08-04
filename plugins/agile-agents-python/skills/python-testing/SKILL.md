---
name: python-testing
description: Add or extend tests for Python code using pytest (the de-facto standard), then run them and chase coverage. USE FOR any request to "write tests for", "add unit tests", "improve coverage", "test this function", "fix failing tests", or after coding work in `.py` files. Defaults to pytest; respects unittest if that's what the project uses.
applies_to: python
---

# Python Testing

You are adding tests (or fixing them) in a Python project. Follow this workflow.

## 1. Detect the existing test framework

- `pyproject.toml` `[tool.pytest.ini_options]`, `pytest.ini`, `tox.ini`, or files matching `test_*.py` / `*_test.py` → **pytest** (default).
- `unittest.TestCase` subclasses → **unittest** (only if pytest is genuinely not in the project; pytest can run unittest tests anyway).

If the SUT is a complex feature, enumerate the cases you should write before starting: happy path, each boundary, each error branch, each documented edge case.

If **no test directory exists**, create `tests/` at the repo root (or `tests/` inside the package if it's a `src/`-layout project), and add a minimal `conftest.py` only if you need shared fixtures.

## 2. Test conventions

- One test module per SUT module: `myapp/parser.py` → `tests/test_parser.py`.
- Function-style tests: `def test_when_input_is_empty_then_returns_default():`.
- Name tests by behavior, not by function name.
- **AAA** layout (Arrange / Act / Assert); one behavior per test.
- No conditionals or loops inside tests. Multiple cases → `@pytest.mark.parametrize`.
- Tests must be order-independent and parallel-safe (`pytest-xdist` compatible).
- Use **fixtures** (`@pytest.fixture`) for setup; scope them as narrowly as possible (`function` > `module` > `session`).
- For exceptions: `with pytest.raises(SpecificError, match=r"expected message"):`.
- For async tests: `pytest-asyncio` (mark `@pytest.mark.asyncio` or set asyncio mode in pyproject).
- Mock only **external** dependencies (HTTP, DB, filesystem). Prefer `monkeypatch` and `tmp_path` fixtures over `unittest.mock` for simple cases.
- Avoid network and real disk I/O; use `tmp_path`, `httpx.MockTransport`, `responses`, or VCR-style cassettes.

## 3. Run tests + coverage

```powershell
# Targeted
pytest tests/test_parser.py::test_when_input_is_empty_then_returns_default -v

# Full
pytest -v

# Coverage (uses pytest-cov)
pytest --cov --cov-report=term-missing --cov-report=annotate:cov_annotate
```

For deeper coverage analysis, use the **`pytest-coverage`** skill (vendored) — it walks the annotated output to identify uncovered lines and prescribes new tests.

## 4. Coverage policy

Aim for 100% coverage of the **lines added or modified** in this session. Don't chase coverage on legacy code unless asked.

## 5. Hand off

When tests pass:

- Summarize: # of new tests, # of fixed tests, current coverage of touched files.
- **Hand off to `review`** with the diff (production code + tests).

## 6. What you do NOT do

- Don't modify production code to make a test pass — push back to `coding`.
- Don't commit.

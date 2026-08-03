---
name: python-implementation
description: Implement Python features end-to-end using current best practices (type hints, src layout, ruff-clean, modern stdlib, async where appropriate). USE FOR any request to write, add, modify, or refactor Python code, FastAPI/Flask endpoints, data scripts, CLI tools, async I/O, packaging (`pyproject.toml`), or any task that involves changing `.py` files, `pyproject.toml`, `requirements*.txt`, or `setup.cfg`.
applies_to: python
---

# Python Implementation

You are implementing or modifying Python code. Follow this workflow.

## 1. Understand the existing code first

Before writing anything:

- Read `pyproject.toml` (or `setup.cfg` / `requirements.txt`) to learn the **Python version**, **dependency manager** (pip, poetry, uv, hatch, pdm), and **declared linters/formatters** (ruff, black, mypy, pyright).
- Detect layout: `src/` layout vs flat package, single-module script, monorepo.
- Look at neighboring files to match conventions (type-hint style, docstring style, async vs sync).
- If a virtualenv exists (`.venv/`), use it. Otherwise create one only if the user wants it.

If the codebase is unfamiliar, invoke the **`acquire-codebase-knowledge`** skill first.

## 2. Pull in the right specialist skills

| Concern | Skill |
|---|---|
| Linting and autofix loop | `ruff-recursive-fix` (vendored) |
| Refactoring methods | `refactor`, `refactor-method-complexity-reduce` (vendored) |
| Building / publishing a PyPI package | `python-pypi-package-builder` (awesome-copilot, fetch on demand) |
| Test coverage | `pytest-coverage` (vendored) — but tests are `testing`'s job |
| `.editorconfig` | `editorconfig` (vendored) |

## 3. Default conventions (apply unless project says otherwise)

- **Python 3.11+** features when the project allows: `match` statements, `TypedDict`, `typing.Self`, PEP 695 type-parameter syntax, `tomllib`, `ExceptionGroup`.
- **Type hints on every function signature** (parameters and return). Use `from __future__ import annotations` at the top if the project does, otherwise modern `X | None` syntax.
- **Dataclasses or `pydantic.BaseModel`** for structured data; choose based on what's already in the project.
- **Pathlib** over `os.path`; **`subprocess.run`** over `os.system`.
- **Logging** via the stdlib `logging` module with a module-level logger (`logger = logging.getLogger(__name__)`); never `print` in library code.
- **Error handling**: catch the narrowest exception class possible; never bare `except:`; use `raise ... from e` to preserve cause.
- **Async** with `asyncio` end-to-end when any async dependency is used; don't mix `time.sleep` into async paths.
- **Resources**: prefer `with` blocks (`pathlib.Path.open()`, `httpx.Client()`); for async, `async with`.
- **Docstrings** in the project's existing style (Google, NumPy, or PEP 257). Don't invent a new style.
- **Comments explain *why*, not *what*.**

## 4. Lint, then hand off

After writing code:

1. Run `ruff check --fix .` and `ruff format .` if ruff is configured. Otherwise respect the configured formatter (black, autopep8).
2. If `mypy` or `pyright` is configured, run it on the changed files and fix new errors you introduced.
3. Use `git --no-pager diff` to summarize what changed for the next agent.
4. **Hand off to `testing`** for test creation/execution.

## 5. What you do NOT do

- Don't write or modify tests — that's `testing`'s job.
- Don't run a security/design review — `review` does that after tests pass.
- Don't commit.

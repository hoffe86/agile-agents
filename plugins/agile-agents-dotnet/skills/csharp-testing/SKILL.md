---
name: csharp-testing
description: Add or extend tests for C#/.NET code using xUnit, NUnit, MSTest, or TUnit (whichever the solution already uses), then run them and pursue coverage. USE FOR any request to "write tests for", "add unit tests", "improve coverage", "test this method", "fix failing tests", or after coding work in a `.cs` project. Detects the existing test framework automatically.
applies_to: dotnet
---

# C# / .NET Testing

You are adding tests (or fixing them) in a C#/.NET solution. Follow this workflow.

## 1. Detect the existing test framework

Look at any `*.Tests.csproj` (or similar) and the package references:

| Packages found | Use skill |
|---|---|
| `xunit`, `xunit.runner.visualstudio` | **`csharp-xunit`** (plugin) |
| `xunit.v3`, `xunit.runner.visualstudio` 3.x | **`csharp-xunit`** (plugin) — note v3 differences |
| `NUnit`, `NUnit3TestAdapter` | **`csharp-nunit`** (plugin) |
| `MSTest.TestFramework`, `MSTest.TestAdapter` | **`csharp-mstest`** (plugin) |
| `TUnit` | **`csharp-tunit`** (plugin) |

If **no test project exists**, create one named `[ProjectName].Tests` next to the SUT, mirror the namespace, and pick the framework that matches the rest of the solution. If the solution is empty of tests, default to **xUnit v3**.

If the SUT is a complex feature, enumerate the cases you should write before starting: happy path, each boundary, each error branch, each documented edge case.

## 2. Test conventions (apply universally)

- One test project per production project: `[ProjectName].Tests`.
- One test class per SUT class: `CatDoor` → `CatDoorTests`.
- Test names describe behavior: `WhenCatMeowsThenCatDoorOpens`.
- **Public instance** classes; no static fields shared between tests.
- **AAA** (Arrange / Act / Assert) layout; one behavior per test.
- No conditionals or loops inside tests. Multiple preconditions → multiple tests; multiple inputs for one behavior → parameterized.
- Tests must be order-independent and parallel-safe.
- Test through **public APIs** only; don't widen visibility, avoid `InternalsVisibleTo`.
- Avoid disk I/O; if unavoidable, use randomized paths under `Path.GetTempPath()` and don't clean up.
- Avoid mocks for code that lives in the same solution; mock external dependencies only. Prefer real objects + in-memory fakes.
- If **FluentAssertions** / **AwesomeAssertions** is already in the solution, use it; otherwise framework-native asserts.
- Use `Throws` / `ThrowsAsync` for exception assertions.

## 3. Run tests + coverage

```powershell
# Run targeted tests
dotnet test --filter "FullyQualifiedName~MyNamespace.CatDoorTests"

# Full run
dotnet test
```

For coverage:

```powershell
# One-time install
dotnet tool install -g dotnet-coverage

# Each run that adds/modifies tests
dotnet-coverage collect -f cobertura -o coverage.cobertura.xml dotnet test
```

Iterate: fix one failing test at a time, then rerun the full suite to confirm no regressions.

## 4. Coverage policy

Aim for 100% coverage of the **lines you added or modified** in this session. Don't chase coverage on legacy code unless the user asks.

## 5. Hand off

When tests pass:

- Summarize: # of new tests, # of fixed tests, current coverage of touched files.
- In `IMPLEMENTATION COMPLETE`, justify every existing-test change in `Existing tests modified`: what the old assertion claimed and why it was invalid.
- **Hand off to `review-lead`** with the diff (production code + tests).

## 6. What you do NOT do

- The invoking `coding` author owns production code and its tests and may fix production logic within the task's scope. Do not self-delegate. Apply `testing-practices` §2: never weaken assertions, delete or skip tests to get green. Prove a test is wrong before changing it and justify that change in the hand-off; if unsure, stop and surface it. Escalate fixes that require a new dependency, contract or design decision.
- Don't commit mid-workflow — commit once the task is complete, not file by file, and never to the default branch.

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

If the SUT is a complex feature, invoke **`breakdown-test`** (vendored) first to enumerate the cases you should write.

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
- **Hand off to `review`** with the diff (production code + tests).

## 6. What you do NOT do

- Don't change production code to make a test pass — push back to `coding` instead. Exception: trivial visibility tweaks that don't change behavior, only when no alternative exists.
- Don't commit.

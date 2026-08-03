---
name: csharp-implementation
description: Implement C#/.NET features end-to-end using current best practices (modern C# language features, async correctness, DI, SOLID, secure-by-default). USE FOR any request to write, add, modify, or refactor C# code, .NET projects, ASP.NET Core APIs, EF Core data access, .NET Aspire workloads, console apps, libraries, or NuGet packages. Also triggered by "implement in C#", ".NET feature", "add endpoint", "add EF migration", "Aspire app", or any task that involves changing `.cs`, `.csproj`, `.sln`, `Directory.Build.*`, or `global.json` files.
applies_to: dotnet
---

# C# / .NET Implementation

You are implementing or modifying C#/.NET code. Follow this workflow.

## 1. Understand the existing code first

Before writing anything:

- Read `global.json`, `Directory.Build.*`, `Directory.Packages.props`, the relevant `.csproj` to learn the **TFM**, **C# language version**, **nullable** setting, and central package management.
- Identify the project type (ASP.NET Core API, console, class library, Aspire host, Worker service, MAUI/WinForms/WPF).
- Look at neighboring files to match existing **conventions** (naming, file-scoped namespaces, primary constructors, record vs class).
- Don't change TFM, SDK, or `<LangVersion>` unless the user asks.

If the codebase is unfamiliar, invoke the **`acquire-codebase-knowledge`** skill first.

## 2. Pull in the right specialist skills

Compose with these skills as needed (most are available as plugins or vendored under `.github/skills/`):

| Concern | Skill |
|---|---|
| Async/await correctness, cancellation, `ConfigureAwait` | `csharp-async` (plugin) |
| General .NET conventions, project hygiene | `dotnet-best-practices` (plugin) |
| ASP.NET Core minimal API + OpenAPI | `aspnet-minimal-api-openapi` (plugin) |
| .NET Aspire orchestration | `aspire` (vendored) |
| EF Core data access | `ef-core` (vendored) |
| Refactoring existing methods | `refactor`, `refactor-method-complexity-reduce` (vendored) |
| Native interop | `dotnet-pinvoke` (plugin) |
| MCP server in C# | `csharp-mcp-server-generator` (plugin) |
| Single-file C# script | `csharp-scripts` (plugin) |
| `.editorconfig` setup | `editorconfig` (vendored) |

## 3. Default conventions (apply unless project says otherwise)

- **Modern C#** when TFM allows: file-scoped namespaces, raw string literals (`"""`), switch expressions, primary constructors, collection expressions, `nameof` with unbound generics.
- **Nullable enabled**; use `ArgumentNullException.ThrowIfNull(x)` and `string.IsNullOrWhiteSpace(x)` for guards.
- **Least-exposure**: `private` > `internal` > `protected` > `public`. Don't add interfaces unless they cross a real seam (external dependency, test boundary).
- **DI everything**; no service locators; constructor injection.
- **Records** for DTOs and value objects.
- **No silent catches**; throw precise exception types (`ArgumentException`, `InvalidOperationException`); never catch `System.Exception` blanket.
- **Async end-to-end**, methods suffixed `Async`, accept `CancellationToken`, no sync-over-async, no fire-and-forget.
- **Structured logging** with `ILogger<T>`; meaningful scopes; no `Console.WriteLine` in libraries.
- **Comments explain *why*, not *what*.** Don't comment self-explanatory code.

## 4. Build, then hand off

After writing code:

1. Run `dotnet build` (or the project's `build.ps1` / `build.cmd` / `Directory.Build.targets` if present). Fix all compile errors and warnings you introduced.
2. Use `git diff` (via PowerShell `git --no-pager diff`) to summarize what changed for the next agent.
3. **Hand off to `testing`** for test creation/execution.

## 5. What you do NOT do

- Don't write or modify tests — that's `testing`'s job. Tell it what behavior needs covering.
- Don't run a security or design review on yourself — `review` does that after tests pass.
- Don't commit. The orchestrator decides commit timing.

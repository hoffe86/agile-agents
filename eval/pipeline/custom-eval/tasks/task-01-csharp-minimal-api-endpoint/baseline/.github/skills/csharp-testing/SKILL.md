---
name: csharp-testing
description: >-
  Task-local xUnit guidance for Orders endpoint tests under tests/Orders.Tests.
---

Use the existing test project and HTTP test host. Assert status and payload for
found and absent orders; isolate test data. Run the declared dotnet test command.
Report missing SDK/restore prerequisites rather than claiming tests passed.

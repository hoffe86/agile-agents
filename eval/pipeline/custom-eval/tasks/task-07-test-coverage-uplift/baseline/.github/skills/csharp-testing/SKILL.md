---
name: csharp-testing
description: >-
  Task-local xUnit and PostgreSQL test guidance for Reconciliation coverage.
---

Test each reconciliation rule through its public API with deterministic fakes.
Keep real PostgreSQL integration tests separate, using disposable Testcontainers.
Use the declared coverage command; do not edit production rules to inflate it.
An unavailable Docker daemon means unverified integration coverage, not a pass.

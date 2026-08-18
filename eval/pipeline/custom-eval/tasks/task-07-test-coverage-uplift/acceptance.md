# Acceptance criteria — task-07

1. **Unit tests pass** — `dotnet test tests/Reconciliation.Tests` is green; class
   `PaymentReconcilerTests` contains ≥ 8 test methods covering all 5 behavioural rules.
2. **Integration test pass** — `dotnet test tests/Reconciliation.IntegrationTests` is
   green; uses a Testcontainers PostgreSQL fixture (not an in-memory DB).
3. **Coverage ≥ 90%** — Coverlet line coverage on `src/Reconciliation/PaymentReconciler.cs`
   is at least 90%, reported in the test run summary.
4. **Deterministic time** — at least one test asserts that `IClock.UtcNow` is the source of
   the journal entry timestamp (e.g., by injecting a fake clock returning a fixed value).
5. **No production code edits** — `PaymentReconciler.cs` and its dependencies are
   unchanged; only test files added.

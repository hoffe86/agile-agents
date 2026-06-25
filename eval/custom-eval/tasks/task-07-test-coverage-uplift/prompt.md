# Task 07 — Add unit + integration test coverage to an existing class

## User story

As a maintainer of the **PaymentReconciler** class in `src/Reconciliation/PaymentReconciler.cs`,
I want comprehensive unit and integration test coverage so future refactors are safe.

## Context

`PaymentReconciler.ReconcileBatchAsync(IEnumerable<Payment> payments, CancellationToken ct)`
currently has zero tests. It depends on:

- `IPaymentRepository` — fetches existing reconciled payments
- `ILedgerClient` — posts journal entries to the accounting system
- `IClock` — for deterministic timestamps

Behavioural rules to cover:

1. Each payment is matched against the repository by `(accountId, externalRef)`.
2. Matched payments are skipped (idempotent re-runs).
3. Unmatched payments produce one journal entry each, posted to `ILedgerClient`.
4. If `ILedgerClient.PostAsync` throws, the batch aborts and the partial state is logged
   but not rolled back (out of scope for this class).
5. Timestamps on journal entries come from `IClock.UtcNow`, not `DateTime.UtcNow`.

## Requested deliverable

1. **Unit tests** in `tests/Reconciliation.Tests/PaymentReconcilerTests.cs` using xUnit + NSubstitute, covering
   all five behavioural rules above. At least 8 test methods total.
2. **Integration test** in `tests/Reconciliation.IntegrationTests/PaymentReconcilerIntegrationTests.cs`
   that uses the real `PaymentRepository` against a `Testcontainers`-managed PostgreSQL and a
   fake `ILedgerClient`, asserting end-to-end that an unmatched payment produces a journal
   entry call.
3. Line coverage on `PaymentReconciler.cs` ≥ 90% as reported by Coverlet.

namespace Reconciliation;

public sealed record Payment(
    string AccountId,
    string ExternalRef,
    decimal Amount,
    string Currency);

public sealed record JournalEntry(
    string AccountId,
    string ExternalRef,
    decimal Amount,
    string Currency,
    DateTimeOffset CreatedAtUtc);

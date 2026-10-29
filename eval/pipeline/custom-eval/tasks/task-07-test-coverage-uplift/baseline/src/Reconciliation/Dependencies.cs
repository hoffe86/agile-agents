namespace Reconciliation;

public interface IPaymentRepository
{
    Task<bool> IsReconciledAsync(
        string accountId,
        string externalRef,
        CancellationToken cancellationToken);

    Task MarkReconciledAsync(
        Payment payment,
        CancellationToken cancellationToken);
}

public interface ILedgerClient
{
    Task PostAsync(JournalEntry entry, CancellationToken cancellationToken);
}

public interface IClock
{
    DateTimeOffset UtcNow { get; }
}

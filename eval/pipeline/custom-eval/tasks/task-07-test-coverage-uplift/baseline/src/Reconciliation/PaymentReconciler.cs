using Microsoft.Extensions.Logging;

namespace Reconciliation;

public sealed class PaymentReconciler(
    IPaymentRepository repository,
    ILedgerClient ledger,
    IClock clock,
    ILogger<PaymentReconciler> logger)
{
    public async Task ReconcileBatchAsync(
        IEnumerable<Payment> payments,
        CancellationToken cancellationToken)
    {
        var postedCount = 0;
        foreach (var payment in payments)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (await repository.IsReconciledAsync(
                    payment.AccountId,
                    payment.ExternalRef,
                    cancellationToken))
            {
                continue;
            }

            var entry = new JournalEntry(
                payment.AccountId,
                payment.ExternalRef,
                payment.Amount,
                payment.Currency,
                clock.UtcNow);
            try
            {
                await ledger.PostAsync(entry, cancellationToken);
            }
            catch (Exception exception)
            {
                logger.LogError(
                    exception,
                    "Reconciliation batch stopped after {PostedCount} journal entries; " +
                    "the batch is not rolled back. Payment {AccountId}/{ExternalRef} failed.",
                    postedCount,
                    payment.AccountId,
                    payment.ExternalRef);
                throw;
            }

            await repository.MarkReconciledAsync(payment, cancellationToken);
            postedCount++;
        }
    }
}

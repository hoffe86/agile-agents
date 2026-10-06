using Npgsql;

namespace Reconciliation;

public sealed class PaymentRepository : IPaymentRepository, IAsyncDisposable
{
    private readonly NpgsqlDataSource _dataSource;

    public PaymentRepository(string connectionString)
    {
        _dataSource = NpgsqlDataSource.Create(connectionString);
    }

    public async Task InitializeAsync(CancellationToken cancellationToken)
    {
        await using var connection = await _dataSource.OpenConnectionAsync(cancellationToken);
        await using var command = new NpgsqlCommand(
            """
            CREATE TABLE IF NOT EXISTS reconciled_payments (
                account_id text NOT NULL,
                external_ref text NOT NULL,
                amount numeric(18, 2) NOT NULL,
                currency char(3) NOT NULL,
                PRIMARY KEY (account_id, external_ref)
            )
            """,
            connection);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task<bool> IsReconciledAsync(
        string accountId,
        string externalRef,
        CancellationToken cancellationToken)
    {
        await using var connection = await _dataSource.OpenConnectionAsync(cancellationToken);
        await using var command = new NpgsqlCommand(
            """
            SELECT EXISTS (
                SELECT 1 FROM reconciled_payments
                WHERE account_id = @accountId AND external_ref = @externalRef
            )
            """,
            connection);
        command.Parameters.AddWithValue("accountId", accountId);
        command.Parameters.AddWithValue("externalRef", externalRef);
        return (bool)(await command.ExecuteScalarAsync(cancellationToken)
            ?? throw new InvalidOperationException("PostgreSQL did not return an existence value."));
    }

    public async Task MarkReconciledAsync(
        Payment payment,
        CancellationToken cancellationToken)
    {
        await using var connection = await _dataSource.OpenConnectionAsync(cancellationToken);
        await using var command = new NpgsqlCommand(
            """
            INSERT INTO reconciled_payments (account_id, external_ref, amount, currency)
            VALUES (@accountId, @externalRef, @amount, @currency)
            ON CONFLICT (account_id, external_ref) DO NOTHING
            """,
            connection);
        command.Parameters.AddWithValue("accountId", payment.AccountId);
        command.Parameters.AddWithValue("externalRef", payment.ExternalRef);
        command.Parameters.AddWithValue("amount", payment.Amount);
        command.Parameters.AddWithValue("currency", payment.Currency);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public ValueTask DisposeAsync() => _dataSource.DisposeAsync();
}

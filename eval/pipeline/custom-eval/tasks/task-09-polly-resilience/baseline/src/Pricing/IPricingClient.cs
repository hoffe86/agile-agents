namespace Pricing;

public interface IPricingClient
{
    Task<QuoteResponse> GetQuoteAsync(
        QuoteRequest request,
        CancellationToken cancellationToken);
}

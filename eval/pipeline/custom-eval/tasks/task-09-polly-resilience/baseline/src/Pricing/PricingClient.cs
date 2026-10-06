using System.Net.Http.Json;

namespace Pricing;

public sealed class PricingClient(HttpClient httpClient) : IPricingClient
{
    public async Task<QuoteResponse> GetQuoteAsync(
        QuoteRequest request,
        CancellationToken cancellationToken)
    {
        using var response = await httpClient.PostAsJsonAsync(
            "/v1/quote",
            request,
            cancellationToken);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<QuoteResponse>(
                cancellationToken: cancellationToken)
            ?? throw new InvalidOperationException("Pricing engine returned an empty response.");
    }
}

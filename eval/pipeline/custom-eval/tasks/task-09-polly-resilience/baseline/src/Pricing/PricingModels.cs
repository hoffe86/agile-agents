namespace Pricing;

public sealed record QuoteRequest(string CustomerId, decimal RequestedCoverage);

public sealed record QuoteResponse(string QuoteId, decimal Premium);

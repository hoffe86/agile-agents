using System.Net;
using System.Net.Http.Json;
using Pricing;
using Xunit;

namespace Pricing.Tests;

public sealed class PricingClientTests
{
    [Fact]
    public async Task GetQuoteAsync_posts_request_and_reads_quote()
    {
        var handler = new StubHandler(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = JsonContent.Create(new QuoteResponse("quote-1", 125.50m))
        });
        var client = new PricingClient(new HttpClient(handler)
        {
            BaseAddress = new Uri("https://pricing.internal")
        });

        var quote = await client.GetQuoteAsync(
            new QuoteRequest("customer-1", 10000m),
            CancellationToken.None);

        Assert.Equal("quote-1", quote.QuoteId);
        Assert.Equal(HttpMethod.Post, handler.Request?.Method);
        Assert.Equal("/v1/quote", handler.Request?.RequestUri?.AbsolutePath);
    }

    private sealed class StubHandler(
        Func<HttpRequestMessage, HttpResponseMessage> responseFactory) : HttpMessageHandler
    {
        public HttpRequestMessage? Request { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Request = request;
            return Task.FromResult(responseFactory(request));
        }
    }
}

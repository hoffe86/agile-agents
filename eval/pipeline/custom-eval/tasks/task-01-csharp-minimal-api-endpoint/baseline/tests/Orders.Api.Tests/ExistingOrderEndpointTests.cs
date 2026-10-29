using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Orders.Api.Domain;
using Xunit;

namespace Orders.Api.Tests;

public sealed class ExistingOrderEndpointTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client;

    public ExistingOrderEndpointTests(WebApplicationFactory<Program> factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task GetOrder_returns_the_full_order()
    {
        var response = await _client.GetAsync(
            "/api/orders/de14a713-b7e0-42a7-8a7c-c497c24b04ce");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var order = await response.Content.ReadFromJsonAsync<Order>();
        Assert.NotNull(order);
        Assert.Equal(OrderStatus.Shipped, order.Status);
    }

    [Fact]
    public async Task GetOrder_returns_problem_details_when_order_is_missing()
    {
        var response = await _client.GetAsync(
            "/api/orders/00000000-0000-0000-0000-000000000000");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.StartsWith(
            "application/problem+json",
            response.Content.Headers.ContentType?.ToString(),
            StringComparison.OrdinalIgnoreCase);
    }
}

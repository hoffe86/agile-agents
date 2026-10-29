using Orders.Api.Domain;

namespace Orders.Api.Endpoints;

public static class OrderEndpoints
{
    public static IEndpointRouteBuilder MapOrderEndpoints(this IEndpointRouteBuilder app)
    {
        var orders = app.MapGroup("/api/orders");
        orders.MapGet("/{id:guid}", GetOrderAsync)
            .WithName("GetOrder")
            .WithSummary("Get a complete order")
            .Produces<Order>()
            .ProducesProblem(StatusCodes.Status404NotFound);
        return app;
    }

    private static async Task<IResult> GetOrderAsync(
        Guid id,
        IOrderRepository repository,
        CancellationToken cancellationToken)
    {
        var order = await repository.GetByIdAsync(id, cancellationToken);
        return order is null
            ? Results.Problem(
                statusCode: StatusCodes.Status404NotFound,
                title: "Order not found",
                type: "https://www.rfc-editor.org/rfc/rfc9457")
            : Results.Ok(order);
    }
}

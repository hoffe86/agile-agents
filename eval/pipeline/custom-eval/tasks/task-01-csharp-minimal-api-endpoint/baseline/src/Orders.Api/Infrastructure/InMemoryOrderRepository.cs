using Orders.Api.Domain;

namespace Orders.Api.Infrastructure;

public sealed class InMemoryOrderRepository : IOrderRepository
{
    private readonly Dictionary<Guid, Order> _orders = new();

    public InMemoryOrderRepository()
    {
        var order = new Order(
            Guid.Parse("de14a713-b7e0-42a7-8a7c-c497c24b04ce"),
            "Example Customer",
            OrderStatus.Shipped);
        _orders.Add(order.Id, order);
    }

    public ValueTask<Order?> GetByIdAsync(Guid orderId, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        _orders.TryGetValue(orderId, out var order);
        return ValueTask.FromResult(order);
    }

    public ValueTask<OrderStatus?> GetStatusAsync(Guid orderId, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return ValueTask.FromResult(
            _orders.TryGetValue(orderId, out var order) ? order.Status : (OrderStatus?)null);
    }
}

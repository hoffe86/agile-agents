namespace Orders.Api.Domain;

public interface IOrderRepository
{
    ValueTask<Order?> GetByIdAsync(Guid orderId, CancellationToken cancellationToken);

    ValueTask<OrderStatus?> GetStatusAsync(Guid orderId, CancellationToken cancellationToken);
}

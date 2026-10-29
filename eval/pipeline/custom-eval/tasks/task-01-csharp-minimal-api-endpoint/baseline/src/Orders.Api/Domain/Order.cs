namespace Orders.Api.Domain;

public sealed record Order(Guid Id, string CustomerName, OrderStatus Status);

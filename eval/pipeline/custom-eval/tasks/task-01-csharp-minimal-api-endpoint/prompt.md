# Task 01 — Add a new C# Minimal API endpoint with xUnit test

## User story

As a developer on the **Orders** service, I need a new endpoint
`GET /api/orders/{id}/status` that returns the current status of an order, so the mobile
app can show users a tracking badge without loading the full order DTO.

## Context

- The service already exposes `/api/orders/{id}` returning the full order.
- Order statuses are an existing enum `OrderStatus { Placed, Paid, Shipped, Delivered, Cancelled }`.
- The status is read from `IOrderRepository.GetStatusAsync(Guid orderId, CancellationToken ct)`,
  which returns `OrderStatus?` (`null` ⇒ order not found).

## Requested change

1. Add the `GET /api/orders/{id}/status` endpoint in the existing minimal-API endpoint group.
2. Return `200 OK` with `{ "status": "Shipped" }` on hit.
3. Return `404 Not Found` (with a Problem Details body, RFC 9457) when the order doesn't exist.
4. Add an xUnit test class `OrderStatusEndpointTests` with at least:
   - one happy-path test (200 + correct status)
   - one not-found test (404 + Problem Details body)
5. Document the endpoint with OpenAPI annotations consistent with the existing endpoints.

Keep the change small — no new abstractions, no repository changes.

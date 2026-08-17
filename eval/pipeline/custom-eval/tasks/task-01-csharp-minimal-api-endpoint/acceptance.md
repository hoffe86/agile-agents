# Acceptance criteria — task-01

1. **Builds** — `dotnet build` succeeds with zero warnings (warnings-as-errors enabled).
2. **Endpoint correct** — `GET /api/orders/{id}/status` returns `200 OK` with body
   `{"status":"<value>"}` for an existing order, and `404 Not Found` with an RFC 9457
   `application/problem+json` body for a missing order.
3. **Tests pass** — `dotnet test` runs the new `OrderStatusEndpointTests` class with at least
   two test methods (happy-path and not-found), and all tests pass.
4. **OpenAPI documented** — endpoint appears in the generated OpenAPI/Swagger document with
   correct response schemas for 200 and 404.
5. **No collateral damage** — no edits to `IOrderRepository`, no new packages added, no
   changes to existing endpoints.

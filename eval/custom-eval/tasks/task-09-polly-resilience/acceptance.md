# Acceptance criteria — task-09

1. **Builds & tests pass** — `dotnet build -warnaserror` and `dotnet test` are green.
2. **Pipeline strategies present** — registration code visibly composes timeout, retry,
   circuit breaker, and concurrency-limiter strategies from
   `Microsoft.Extensions.Http.Resilience` (v8+) or `Polly.Core`.
3. **Retry config matches spec** — 3 retries, exponential backoff with jitter, retries on
   the specified status codes; honours `Retry-After` (verifiable by code reading or a test).
4. **Options class exists** — `PricingClientResilienceOptions` is bindable via
   `IOptions<>`; values are not hardcoded inside the registration.
5. **Behaviour tested** — at least two new tests in `PricingClientResilienceTests.cs`: one
   asserts retry on 503, one asserts the 2 s per-attempt timeout fires.

# Task 09 — Implement Polly resilience patterns on an HTTP client

## User story

As a service owner, I need our typed HTTP client `IPricingClient` (which calls the upstream
pricing engine over HTTPS) to be resilient to transient failures, so brief upstream blips
don't manifest as user-visible errors.

## Context

- The client is registered today with `services.AddHttpClient<IPricingClient, PricingClient>()`.
- It calls `POST https://pricing.internal/v1/quote` with a JSON body and expects a JSON response.
- Upstream SLO is "99% of requests in < 250 ms"; the long tail is up to 2 s.
- Upstream returns `429` on rate-limit and `503` on planned restarts.

## Requested change

Wrap the registration with a Polly v8 (`Microsoft.Extensions.Http.Resilience` /
`ResiliencePipelineBuilder`) pipeline that includes:

1. **Timeout** — per-attempt timeout of 2 seconds.
2. **Retry** — 3 retries with exponential backoff + jitter, retrying on `HttpRequestException`,
   5xx, 408, and 429. Honour the `Retry-After` header on 429/503 if present.
3. **Circuit breaker** — opens after 5 consecutive failures within 30 s, stays open for
   15 s, then half-opens.
4. **Bulkhead / concurrency limiter** — at most 50 in-flight calls; queue depth 100.

Pipeline must be configurable via `IOptions<PricingClientResilienceOptions>` so adopters
can override values without recompiling.

Add or update unit tests in `tests/Pricing.Tests/PricingClientResilienceTests.cs` that use
a fake `HttpMessageHandler` to verify the retry-on-503 and timeout behaviours.

# ADR 0007: Use Polly for HTTP client resilience

## Status

Accepted.

## Context

HTTP calls from service clients need bounded retries and circuit breaking for transient
failures. The service currently uses `HttpClient` and needs a consistent resilience policy.

## Decision

Use Polly directly to compose retry, timeout, and circuit-breaker policies around outbound
HTTP requests.

## Consequences

- Teams can use Polly's established policy model across HTTP clients.
- Teams own the integration and configuration between Polly and `HttpClient`.

## Alternatives

- A hand-written `DelegatingHandler` was rejected because policy behavior would be duplicated.
- The platform HTTP resilience package was not selected at the time this decision was made.

## Related decisions

- None.

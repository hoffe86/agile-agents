# 0007. Use Polly for HTTP Client Resilience

- Status: accepted
- Date: 2026-01-12
- Deciders: Service team

## Context and Problem Statement

HTTP calls from service clients need bounded retries and circuit breaking for transient
failures. The service currently uses `HttpClient` and needs a consistent resilience policy.

## Decision Drivers

- Bound transient-failure retries and isolate a failing downstream service.
- Reuse the team's existing Polly pipeline expertise.

## Considered Options

- Polly directly
- A hand-written DelegatingHandler

## Decision Outcome

Chosen option: **"Polly directly"**, because the team can compose retry, timeout, and
circuit-breaker policies consistently using its existing pipeline expertise.

### Positive Consequences

- Teams can use Polly's established policy model across HTTP clients.

### Negative Consequences

- Teams own the integration and configuration between Polly and `HttpClient`.

## Pros and Cons of the Options

### Polly directly

- Good, because reusable pipelines avoid repeating resilience policy in each client.
- Bad, because custom integration must be maintained as HTTP client registration evolves.

### A hand-written DelegatingHandler

- Good, because the team controls every retry without another library's abstractions.
- Bad, because policy behavior would be duplicated and cancellation bugs become our burden.

## Links

- [Polly documentation](https://github.com/App-vNext/Polly)

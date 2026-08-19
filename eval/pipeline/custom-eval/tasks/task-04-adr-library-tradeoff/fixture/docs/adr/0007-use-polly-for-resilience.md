# 0007. Use Polly directly for HTTP resilience

- Status: accepted
- Date: 2025-11-04
- Deciders: Tech Lead, Service Team
- Consulted: Platform Engineering
- Informed: All service maintainers

Technical Story: Pick a resilience approach for outbound HTTP calls in the service estate.

## Context and Problem Statement

Our services make outbound HTTP calls that fail transiently — timeouts, 503s, brief
connection resets. Each team was handling this differently: some retried in a `catch`,
some not at all. We need one approach teams can copy. Which resilience library should we
take a direct dependency on?

## Decision Drivers

- One documented approach across every service, rather than per-team improvisation.
- Full control over retry, circuit-breaker and timeout policy shape.
- Maturity and community familiarity — we want answers to exist when something breaks.

## Considered Options

1. **Polly v8 directly** — take the dependency and compose pipelines by hand.
2. **Hand-rolled `DelegatingHandler`** — write our own retry/circuit-breaker.

## Decision Outcome

Chosen option: **Polly v8 directly**, because it gives us the full pipeline DSL and the
widest body of community knowledge, at the cost of every service having to wire its own
policies.

### Positive Consequences

- Complete control over policy composition per call-site.
- Large community, extensive documentation and samples.

### Negative Consequences

- Every service wires its own policies, so "consistent" depends on review discipline
  rather than on a default — drift is likely as the estate grows.
- No opinionated defaults means new services start from a blank page.

## Links

- [Polly on GitHub](https://github.com/App-vNext/Polly)

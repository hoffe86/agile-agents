---
name: cloud-native-patterns
description: >-
  Neutral resilience, consistency, 12-Factor, observability and API contracts
  for external boundaries, shared resources and deployables. Authors apply;
  specialist reviewers check without executing author workflows.
metadata:
  applies_to: all
---

# Cloud-native patterns

## When to apply

Apply unconditionally when the change involves any of:

- An HTTP / gRPC / message-bus boundary (in or out).
- A shared resource: database, cache, blob store, queue, external API.
- Long-running work, retries, batching, scheduling.
- A new service, a new deployable unit, or a change to startup/shutdown.
- Background workers, hosted services, message handlers.

Skip for pure in-process refactors with no external boundary.

## 1. Pattern catalogue

Cite by name. Reinventing one of these instead of using a vetted implementation
is a 🟠 Major review finding.

**Resilience & traffic management**

- **Retry** — transient failures only; bounded attempts with exponential backoff
  + full jitter; never retry non-idempotent POST without an idempotency key.
- **Circuit Breaker** — open after N failures over window; half-open probe;
  fail-fast when open. Wrap every outbound dependency.
- **Bulkhead** — isolate pools (HTTP clients, threads, DB connections) per
  downstream so one slow dependency cannot exhaust the rest.
- **Timeout** — every outbound call has an explicit timeout; default = caller
  budget − safety margin. No infinite waits.
- **Throttling / Rate limiting** — protect both ingress and egress; return 429
  with `Retry-After` upstream.
- **Queue-Based Load Levelling** — buffer spikes via queue between producer and
  worker; smooths bursts without overprovisioning.
- **Health Endpoint Monitoring** — expose `/health/live` (liveness) and
  `/health/ready` (readiness, includes dependency probes); shallow vs deep.

**Data & consistency**

- **Cache-Aside** — read-through, write-invalidate; never trust the cache as
  source of truth. Set TTL + max size.
- **Materialised View** — precompute query-shaped projections; don't query the
  write model for read-heavy paths.
- **CQRS** — separate write model and read model when they diverge; not a
  default — apply when justified.
- **Event Sourcing** — append-only event log as system of record; needs
  snapshots and projections; high cost, high benefit when applicable.
- **Outbox** — write the domain change and the outgoing event in the **same
  database transaction**; a relay publishes from the outbox table. Never
  dual-write to DB and broker.
- **Inbox / dedup** — deduplicate inbound messages by message-id within a
  bounded window; required for at-least-once delivery.
- **Idempotency Key** — clients send a key; server stores `key → response` for a
  TTL and returns the cached response on retry. Mandatory on non-idempotent
  HTTP that callers may retry.
- **Saga** — long-running distributed workflow as a series of local
  transactions + compensations. Choreography (event-driven) or orchestration
  (central coordinator). **Never use 2PC across services.**
- **Compensating Transaction** — explicit undo step for each saga step that
  cannot be rolled back natively.

**Modernisation & boundaries**

- **Strangler Fig** — incrementally replace a legacy system route-by-route
  behind a façade.
- **Anti-Corruption Layer (ACL)** — translate at the boundary to a downstream
  with a different model; protect the domain from leaking foreign concepts.
- **Branch by Abstraction** — refactor in-place behind an interface, swap
  implementations gradually (preferred over long-lived feature branches).
- **Sidecar / Ambassador** — out-of-process helpers (proxy, telemetry, secret
  fetcher) deployed alongside the service.
- **Gateway Aggregation / Routing / Offloading** — gateway responsibility, not
  service responsibility (auth, rate limiting, request shaping).
- **Backends-for-Frontends (BFF)** — per-experience aggregation layer; keeps
  client-specific shaping out of the core service.

## 2. Twelve-Factor cloud-native readiness

Treat as hard rules for any deployable. Violations are 🟠 Major.

1. **Codebase** — one repo (or sub-tree) per deployable; many deploys.
2. **Dependencies** — declared, versioned and isolated using the solution's
   manifests and lockfiles; no implicit system dependencies.
3. **Config** — in the solution's configuration / secrets stores; **never** in
   code or committed config files for sensitive values.
4. **Backing services** — treated as attached resources (connection-string in
   config, swappable per environment).
5. **Build / release / run** — strictly separate; the artifact is immutable
   once built.
6. **Processes** — stateless; persist state in backing services. No in-memory
   session affinity.
7. **Port binding** — service exposes itself on a port; no relying on a
   container-side reverse proxy embedded in the app process.
8. **Concurrency** — scale via process model (more pods / instances), not by
   bigger boxes alone.
9. **Disposability** — fast startup (< 10 s ideal); **graceful shutdown** on
   `SIGTERM`: stop accepting new work, drain in-flight work, close connections,
   flush logs/metrics within the platform's grace period.
10. **Dev/prod parity** — same backing services, same versions, same image.
11. **Logs** — structured JSON to stdout; the platform aggregates. No file
    logging from the app.
12. **Admin processes** — one-off jobs run as the same release in the same
    environment.

## 3. Resilience implementation contract

- Use the solution's established implementation, not a harness-selected package.
  Verify bounded retries, jitter, transient-error classification, circuit
  recovery and isolation against the actual dependency's failure modes.
- Pool reusable clients and connections; bound connect/read/write/pool waits.
- Propagate cancellation from caller to downstream and background operations.
  Do not hide cancellation or block an asynchronous execution context.
- Observe background failures; define ownership, shutdown and backpressure.
- Validate configuration at startup. Resource lifetimes must be compatible:
  no long-lived owner retaining a short-lived dependency.
- Project only required data, avoid N+1 queries and tracking when unnecessary,
  and paginate or stream bounded results.

## 4. Solution capability boundary

Select implementation guidance by available description **and** applicability
to the task, path, runtime/version and provider. Do not equate on-disk files
with granted runtime capabilities. Without a match, use existing repo
conventions and authoritative documentation, and report that fallback.
No framework, package, exporter or cloud provider is selected by this skill.
Reviewers read these contracts; they never execute an author workflow.

## 5. Observability defaults

Use the solution's telemetry implementation and declared sinks. OpenTelemetry
and W3C Trace Context are interoperable references, not package/provider mandates.

- **Three signals.** Traces, metrics, logs — correlated with
  shared resource attributes (`service.name`, `service.version`,
  `deployment.environment`).
- **Context propagation.** W3C `traceparent` + `tracestate` headers in **every**
  outbound HTTP / messaging call. Never invent a custom correlation header.
- **Structured logging.** Use the solution's logger. Log fields, not
  concatenated strings. No PII in logs. No secrets in logs (token, key,
  password, connection-string, Authorization header).
- **Metrics** — record the RED signals (Rate, Errors, Duration) per endpoint
  and per outbound dependency; counter + histogram. Use
  [OTel semantic conventions](https://opentelemetry.io/docs/specs/semconv/) for
  metric names — don't invent ad-hoc naming.
- **Spans** — one span per logical operation; record exceptions and set status
  correctly through the solution's instrumentation API.
- **Health endpoints** — `/health/live` (process up) and `/health/ready`
  (dependencies reachable). Liveness must **never** depend on a downstream — if
  it does, the downstream's outage takes you down.

## 6. HTTP / gRPC API hygiene

- **Errors** — return [RFC 9457 Problem Details](https://datatracker.ietf.org/doc/html/rfc9457)
  (`application/problem+json`) where the API contract uses it. Never return raw
  stack traces; preserve the solution's public error contract.
- **Status codes** — use the precise code (201 + `Location` for create, 202 for
  async accept, 204 for empty success, 400 vs 422, 409 for conflict, 412 for
  ETag mismatch, 429 with `Retry-After`, 503 with `Retry-After`). Do not return
  200 with an error body.
- **Idempotency** — `PUT` and `DELETE` are idempotent by spec. Make `POST`
  idempotent via `Idempotency-Key` header when retries are expected.
- **Concurrency** — `ETag` + `If-Match` for optimistic concurrency on updates.
- **Versioning** — URL segment (`/v1/...`), header, or media-type — pick one
  per repo; document. Do not mix.
- **Pagination** — cursor-based for stable lists; `?limit=` + `?cursor=`. Cap
  page size server-side. **Never** return an unbounded list.
- **Documentation** — every endpoint has request schema, all response codes and
  examples in the solution's API specification; verify it matches behavior.
- **gRPC** — deadlines on every call; cancellation propagated; status codes
  per [google.rpc.Code](https://grpc.io/docs/guides/status-codes/); reflection
  disabled in production.

## 7. Anti-patterns (line-level — flag in review)

- **Hand-rolled retries** → established solution mechanism with bounded policy.
- **Fresh client per call / no timeout** → reuse pooled resources and bound waits.
- **Sync-over-async** → keep the execution chain asynchronous.
- **Unobservable background work** → explicit ownership and error propagation.
- **Missing cancellation** → accept and propagate the caller's signal.
- **String-concatenated logs** → structured fields.
- **Secret / token / Authorization header in logs** → mask or omit.
- **Unbounded query** on user input → paginate.
- **Lazy loading inside a loop** (N+1) → bounded joins or projection.
- **Ambiguous local timestamps** → explicit UTC/offsets.
- **Culture-sensitive machine-format parsing** → explicit invariant format.
- **Captive dependency** → align ownership with resource lifetime.
- **Dual-write to DB + broker** outside the same transaction → Outbox pattern.
- **Liveness probe queries the database** → readiness, not liveness.
- **Catch-and-log-and-continue** that hides failures from the caller → either
  handle meaningfully or let it propagate.
- **Returning error string as a result** instead of throwing or returning a
  `Result<T, E>` / `OperationResult` → use the language idiom.

## 8. References (cite these in findings / ADRs)

- **Azure Cloud Design Patterns** — https://learn.microsoft.com/azure/architecture/patterns/
- **Azure Well-Architected Framework** — https://learn.microsoft.com/azure/well-architected/
- **microservices.io patterns** — https://microservices.io/patterns/
- **The Twelve-Factor App** — https://12factor.net/
- **OpenTelemetry semantic conventions** — https://opentelemetry.io/docs/specs/semconv/
- **W3C Trace Context** — https://www.w3.org/TR/trace-context/
- **RFC 9457 — Problem Details for HTTP APIs** — https://datatracker.ietf.org/doc/html/rfc9457
- **Polly / Microsoft.Extensions.Http.Resilience** — https://www.pollydocs.org/ ; https://learn.microsoft.com/dotnet/core/resilience/http-resilience
- **tenacity** — https://tenacity.readthedocs.io/
- **CNCF Cloud Native Definition** — https://github.com/cncf/toc/blob/main/DEFINITION.md

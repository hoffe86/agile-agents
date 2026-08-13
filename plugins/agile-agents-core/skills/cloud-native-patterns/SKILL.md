---
name: cloud-native-patterns
description: >-
  Canonical reference for cloud design patterns, resilience defaults, 12-Factor
  cloud-native readiness, observability, and HTTP/gRPC API hygiene used by the
  authoring and review agents. Distils Microsoft Azure Cloud Design Patterns,
  microservices.io, the Twelve-Factor App, OpenTelemetry semantic conventions,
  and IETF RFC 9457 (Problem Details) into agent-actionable defaults and
  anti-patterns. Loaded by coding (apply), review and
  architecture-reviewer (check).
applies_to: all
---

# Cloud-native patterns

This skill is **applied** by authoring agents (`coding`,
`infrastructure`) and **checked** by review agents (`review-lead`,
`architecture-reviewer`). It is intentionally short and reference-shaped —
not a tutorial. Look up the citation when you need depth.

## When to apply

Apply unconditionally when the change involves any of:

- An HTTP / gRPC / message-bus boundary (in or out).
- A shared resource: database, cache, blob store, queue, external API.
- Long-running work, retries, batching, scheduling.
- A new service, a new deployable unit, or a change to startup/shutdown.
- Background workers, hosted services, message handlers.

Skip for pure in-process refactors with no external boundary.

## 1. Pattern catalogue (Azure Cloud Design Patterns + microservices.io)

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
2. **Dependencies** — declared and isolated (`*.csproj`, `requirements.txt` /
   `pyproject.toml`, `package.json` lockfile committed); no implicit system deps.
3. **Config** — in environment / Key Vault / App Configuration; **never** in
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

## 3. Resilience defaults — .NET

- **HttpClient** — always via `IHttpClientFactory` (named or typed clients);
  never `new HttpClient()` per call. Configure `Timeout`, default headers, and
  `User-Agent` at registration.
- **Resilience pipeline** — use **Microsoft.Extensions.Http.Resilience**
  (`AddStandardResilienceHandler` for HTTP, or `ResiliencePipelineBuilder` from
  Polly v8 for custom). Standard pipeline = retry (with jitter) + circuit
  breaker + timeout + bulkhead. Do **not** hand-roll retries.
- **Cancellation** — every async public method on a long-running surface
  accepts `CancellationToken` and propagates it. Honour
  `HttpContext.RequestAborted` in controllers / minimal-API handlers.
- **Async correctness** — async-all-the-way. Forbidden: `.Result`, `.Wait()`,
  `Task.Run` to escape sync, `async void` (except event handlers). In **library**
  code, await with `.ConfigureAwait(false)`.
- **Lifetimes** — singletons must not depend on scoped (captive dependency).
  `DbContext` is scoped. `IHttpClientFactory` is singleton; the `HttpClient` it
  hands out is short-lived.
- **EF Core** — `AsNoTracking()` on read paths; project to DTOs (`Select`)
  rather than materialising entities; explicit `Include` over lazy loading;
  paginate (`Skip`/`Take`) any unbounded query touched by user input;
  `IAsyncEnumerable` for streaming.
- **Options pattern** — `IOptions<T>` (singleton snapshot) /
  `IOptionsSnapshot<T>` (per request) / `IOptionsMonitor<T>` (live reload).
  Validate on startup with `.ValidateDataAnnotations().ValidateOnStart()`.

## 4. Resilience defaults — Python

- **httpx** over `requests` for new code (sync + async, HTTP/2, timeouts
  first-class). Always set `httpx.Timeout(connect=…, read=…, write=…, pool=…)`.
- **tenacity** for retries — `retry`, `stop_after_attempt`,
  `wait_exponential_jitter`, `retry_if_exception_type`. Never hand-roll a retry
  loop.
- **circuitbreaker** or `pybreaker` for circuit breakers; pair with tenacity.
- **asyncio cancellation** — accept and propagate `asyncio.CancelledError`;
  never swallow it. Use `asyncio.timeout()` (3.11+) for bounded waits.
- **Concurrency primitives** — `asyncio.Semaphore` for bulkheads;
  `asyncio.Queue` for backpressure between producers and workers.
- **Settings** — `pydantic-settings` for typed config from env / `.env`; never
  read `os.environ` directly in business logic.
- **HTTP server** — FastAPI + uvicorn/hypercorn; lifespan handlers for
  start/shutdown; use `BackgroundTasks` for fire-and-forget within a request.

## 5. Observability defaults

Use OpenTelemetry. Vendor-agnostic by default; export to Application Insights /
Azure Monitor via OTLP.

- **Three signals.** Traces, metrics, logs — all emitted from the same SDK with
  shared resource attributes (`service.name`, `service.version`,
  `deployment.environment`).
- **Context propagation.** W3C `traceparent` + `tracestate` headers in **every**
  outbound HTTP / messaging call. Never invent a custom correlation header.
- **Structured logging.** Use the platform logger (.NET `ILogger<T>`, Python
  `logging` with `structlog` or `python-json-logger`). Log fields, not strings:
  ```csharp
  _logger.LogInformation("Order {OrderId} accepted for customer {CustomerId}", id, customerId);
  ```
  No string concatenation. No PII in logs. No secrets in logs (token, key,
  password, connection-string, Authorization header).
- **Metrics** — record the RED signals (Rate, Errors, Duration) per endpoint
  and per outbound dependency; counter + histogram. Use
  [OTel semantic conventions](https://opentelemetry.io/docs/specs/semconv/) for
  metric names — don't invent ad-hoc naming.
- **Spans** — one span per logical operation; record exceptions with
  `Activity.RecordException` / `span.record_exception`; set status correctly.
- **Health endpoints** — `/health/live` (process up) and `/health/ready`
  (dependencies reachable). Liveness must **never** depend on a downstream — if
  it does, the downstream's outage takes you down.

## 6. HTTP / gRPC API hygiene

- **Errors** — return [RFC 9457 Problem Details](https://datatracker.ietf.org/doc/html/rfc9457)
  (`application/problem+json`). Never return raw stack traces. In ASP.NET use
  `ProblemDetails` + `IProblemDetailsService`; in FastAPI raise `HTTPException`
  and shape via an exception handler.
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
- **Documentation** — OpenAPI / `Microsoft.AspNetCore.OpenApi` /
  Swashbuckle / FastAPI auto-schema; every endpoint has request schema, all
  response codes, and an example.
- **gRPC** — deadlines on every call; cancellation propagated; status codes
  per [google.rpc.Code](https://grpc.io/docs/guides/status-codes/); reflection
  disabled in production.

## 7. Anti-patterns (line-level — flag in review)

- **Hand-rolled retry loop** (`for i in range(3): try: ... except: time.sleep(2**i)`)
  → use Polly / tenacity.
- **HttpClient without timeout** or **`new HttpClient()` per call** → typed
  client + resilience handler.
- **Sync-over-async** (`task.Result`, `task.Wait()`, `task.GetAwaiter().GetResult()`,
  `asyncio.run()` inside an already-running loop) → make the call site async.
- **`async void`** outside event handlers → return `Task`.
- **Missing `CancellationToken` on async public surface** → add it; propagate.
- **String-concatenated log message** (`$"User {id} did X"` in `LogInformation`)
  → use the message-template overload.
- **Secret / token / Authorization header in logs** → mask or omit.
- **Unbounded query** on user input (`.ToListAsync()` without `Take`) → paginate.
- **Lazy loading inside a loop** (N+1) → `Include` or projection.
- **`DateTime.Now` / `datetime.now()`** for timestamps → `DateTimeOffset.UtcNow`
  / `datetime.now(timezone.utc)`.
- **Culture-sensitive parsing** (`int.Parse(s)` without `CultureInfo.InvariantCulture`)
  on machine-format inputs → use invariant culture.
- **Singleton holds scoped dependency** (captive dependency) → inject
  `IServiceScopeFactory` or `IServiceProvider` and create a scope.
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

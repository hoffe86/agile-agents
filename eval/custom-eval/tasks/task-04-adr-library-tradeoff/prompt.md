# Task 04 — Generate an ADR for a chosen library trade-off

## User story

As the tech lead on a new C# microservice, I need an Architecture Decision Record that
documents our choice of HTTP-resilience library so future maintainers understand the
trade-off, not just the outcome.

## Context

The team is choosing between three options for HTTP-client resilience:

1. **Polly** (v8) — battle-tested, rich pipeline DSL, well-known in .NET community
2. **Microsoft.Extensions.Http.Resilience** — Microsoft-shipped, opinionated, narrower API
3. **Roll-your-own** — `HttpMessageHandler` with manual retry / circuit-breaker logic

We have decided on **Microsoft.Extensions.Http.Resilience**, but the previous ADR-0007
recommended Polly directly, so this decision **supersedes** ADR-0007.

## Requested deliverable

A single Markdown file `docs/adr/0014-http-resilience-library.md` that:

1. Follows our MADR-style ADR template (we use the lightweight one — Status / Context /
   Decision / Consequences / Alternatives / Related decisions).
2. Numbers the ADR as `0014` and supersedes `0007`.
3. Explains the **trade-off**, not just the conclusion. For each rejected option, state
   what we lose by not picking it.
4. Lists at least two consequences (one positive, one negative).
5. References the relevant Microsoft Learn / GitHub URLs for the chosen library.

No code changes required for this task — it is a documentation deliverable.

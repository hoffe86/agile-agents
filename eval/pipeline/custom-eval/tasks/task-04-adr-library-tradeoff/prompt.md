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

Exactly two working-copy ADR files are in scope:

1. Add `docs/adr/0014-http-resilience-library.md` following the **MADR** template selected
   by `documentation.adr.format` in the task profile and defined by the
   `architecture-decision-records` skill (not Nygard or a custom six-section template).
2. Record that ADR-0014 supersedes ADR-0007 with a relative Markdown link in **Links**.
   Update only `docs/adr/0007-http-resilience-library.md` to status **superseded** with a
   relative Markdown link forward to ADR-0014; preserve its historical rationale.
3. Explains the **trade-off**, not just the conclusion. For each rejected option, state
   what we lose by not picking it.
4. Lists at least two consequences (one positive, one negative).
5. References the relevant Microsoft Learn / GitHub URLs for the chosen library.

No other file changes are permitted. The canonical sibling baseline is immutable:
update only the working-copy predecessor, never the original comparison input.

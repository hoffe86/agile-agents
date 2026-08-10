---
name: engineering-standards
description: >-
  The engineering quality bar every agent in the suite works to — Clean Code, SOLID, DDD,
  Clean Architecture, security-by-default, error handling, immutability, configuration over
  hardcoding, Infrastructure-as-Code and pipeline hygiene, plus the mandatory pre-PR
  self-review checklist. Technology-neutral: the same bar applies in any language,
  framework, or platform. USE ON EVERY task that writes, reviews, or designs anything —
  code changes, reviews, architecture decisions, refactoring, IaC, CI/CD, documentation,
  naming. Load it silently and apply it; do not echo it back to the user.
applies_to: all
---

# Engineering Standards

The bar for production-grade work in this suite. Technology-neutral — the same standards
apply regardless of language, framework, or platform.

Work is expected to be **well-architected and production-grade**. Security by default,
observability, reliability, scalability, and maintainability are non-negotiable, whatever
the project type or technology choice.

> **Team conventions beat this file.** Where the repository's own instructions or
> `solution-profile.yaml` state a convention, follow that. These standards fill the gaps;
> they don't override a project that has already decided.

## Core principles

- **Think first, then answer** — reason through the problem before responding. Consider
  edge cases, trade-offs, and implications. Never rush to a surface-level answer.
- **Research before proposing** — investigate the codebase, existing patterns, and
  framework documentation before suggesting a solution. Never guess from memory. If a
  newer approach or library version is genuinely better, recommend it with the trade-off
  stated.
- **Security by default** — every feature, endpoint, and data flow is secure from the
  start, not bolted on later. Minimal permissions, input validation, auth/authz enforced,
  secrets in vaults, dependencies audited.
- **Standards before custom solutions** — prefer established standards, protocols, and
  built-in framework capabilities. Build custom only when no suitable standard exists.

## Design principles

- **Clean Code** — meaningful names, small focused functions, single responsibility, no
  dead code. Readability over cleverness. Only comment *why*.
- **Domain-Driven Design** — bounded contexts, ubiquitous language in types and method
  names, aggregates own their invariants.
- **Microservice thinking** — loosely coupled via interfaces, contract-first APIs,
  independently deployable, infrastructure automated.
- **SOLID** — depend on abstractions not implementations, open for extension, one reason
  to change per class.
- **Clean Architecture** — dependencies point inward, domain at the centre, infrastructure
  at the edges.

## Code practices

- **Language-idiomatic patterns** — follow the conventions of whichever language and
  framework the project uses.
- **Error handling & logging** — never swallow errors silently. Let exceptions propagate to
  the correct handler layer. Use structured logging with appropriate levels. Never return
  error strings as results.
- **Favour immutability** — prefer immutable data structures, readonly fields, and value
  types for data models.
- **Configuration over hardcoding** — magic numbers and strings belong in configuration or
  named constants, not inline in method bodies.
- **Selective data fetching** — request only the properties actually used in the result
  mapping. Avoid fetching whole objects when a subset suffices.

## Operational practices

- **Infrastructure as Code** — automate all resources, identity, networking, CI/CD config,
  and secrets management. No manual steps for recurring operations: it is what makes a
  deployment reproducible and prevents environment drift.
- **Secure pipelines** — workload identity / federated credentials for CI/CD, secrets in a
  vault linked to compute — never in IaC state or plain environment variables.
- **Self-contained repositories** — each repo independently deployable. No cross-repo writes
  from one deployment into another's config. Resolve cross-repo values dynamically via data
  sources and naming conventions.
- **CI/CD** — reusable workflows, environment chaining with gating before production, build
  once and promote the same artifact across environments.
- **Automated formatting** — enforce format checks in CI on every PR, so code review never
  spends time on style.

## Pre-PR self-review (mandatory)

Before a pull request is opened, self-review the change against the standards above. This
catches issues before CI and reviewers see them. `review` also uses this list as the
structure for its general code-quality pass.

1. **Build & checks pass locally** — full build, tests, lint, and format checks. Never push
   code that doesn't compile or pass locally.
2. **Standards compliance** — Clean Code, SOLID, DDD, and Clean Architecture principles
   followed.
3. **Security** — no secrets in code, minimal permissions, inputs validated, no injection or
   XSS vectors, auth/authz enforced, tokens correctly scoped, dependencies checked for known
   vulnerabilities.
4. **Edge cases** — null handling, empty collections, error paths tested.
5. **No regressions** — existing tests pass, no unintended side effects.
6. **Documentation** — instructions and comments updated if the change affects architecture,
   setup, or public APIs.

## Documentation

- Update docs on **every essential change** — architecture, setup, environment variables,
  CI/CD, cross-repo dependencies. Don't defer to a follow-up task.
- Don't document file-level project structure — it changes too often to stay true.

## Naming & organisation

- **Consistent resource naming** — type, domain, service, stage, and region segments,
  following whatever convention `solution-profile.yaml` declares.
- **IaC file organisation** — logical file separation, consistent variable naming.

## Anti-patterns

- Don't suggest a complex solution when a simple one works.
- Don't hardcode values that a data source can resolve.
- Don't add a wrapper layer when the framework already has built-in support.
- Don't leave dead code or TODO comments without an action behind them.
- Don't create a separate endpoint or tool when an existing one can be extended with a
  parameter.
- Don't commit to the default branch, and don't open a PR without approval. (Read-only
  review agents commit nothing at all — see `reviewer-read-only-rules`.)

---
name: development-practices
description: >-
  The implementation half of the build-and-verify craft — smallest-change bias,
  no speculative generality, cloud-native and observability defaults, error
  handling, documentation-in-the-same-change, language-skill routing, and the
  build/lint/startup verification an implementation must pass before it is
  handed off. Technology-neutral: routes to whichever language implementation
  skill the project installed and falls back to the repo's own conventions when
  none is. Loaded by the `coding` agent on every task that changes production
  code, alongside `testing-practices` (its verification half). USE FOR: writing
  a feature, fixing a bug, refactoring, integrating a library, migrating a
  framework version. DO NOT USE FOR: writing the tests that cover the change
  (that is `testing-practices`), Infrastructure-as-Code (that is
  `iac-best-practices` and the infrastructure agent), or reviewing someone
  else's diff (that is `code-review-checklist`).
applies_to: all
---

# Development practices

The craft bar for changing production code. Paired with **`testing-practices`** —
one agent loads both, because whoever writes the code owns proving it works.
This skill covers everything up to "the change is correct and builds";
`testing-practices` covers everything that demonstrates it.

`engineering-standards` (Clean Code, SOLID, DDD, Clean Architecture,
standards-before-custom, configuration-over-hardcoding, security-by-default,
favour-immutability) is assumed and **not restated here**. What follows are the
implementation-specific deltas.

## 1. Craft bias

- **Smallest change that fully solves it.** Extend the pattern already in this
  file/module before introducing a new one. Prefer: existing repo pattern >
  standard library / platform feature > already-installed dependency > new
  dependency. A new dependency, boundary, contract, or cloud service is *not
  yours to add* — report it in `Open questions for review` and stop (the
  orchestrator routes it to `architect`).
- **No speculative generality.** No interface with one implementation, no
  factory for one product, no config knob for a value that never changes, no
  extension point "for later". If you think it's coming, say so in the hand-off
  — don't build it.
- **Boring over clever.** Clever is what someone decodes at 3am. If a reviewer
  needs the commit message to understand the code, simplify the code.
- **Deletion counts as implementation.** If the request is satisfiable by
  removing code, do that instead of adding.
- **Never simplify away correctness.** Input validation at trust boundaries,
  error handling that prevents data loss, authn/authz, secrets handling, and
  accessibility basics are non-negotiable regardless of how small the change is.

## 2. Research before proposing

Read the surrounding code first; never write from memory. If a newer framework
feature or library version is genuinely better, recommend it *with trade-offs*
rather than silently adopting it.

**Look it up rather than assume it.** When an API signature, default, option
name, version behaviour, or limit would change what you write and you are not
certain of it, verify before writing — the repo's own usage and lockfiles
first, then `context7/*` / `microsoft-docs/*` / `web` / a browser
(`read-repo-context` §9). A plausible-looking call that doesn't exist in the
pinned version costs a build, a gate, and a corrective round to discover. If you
couldn't verify, name the fact you assumed in the hand-off rather than leaving
it silent.

For an unfamiliar codebase, invoke `acquire-codebase-knowledge` first. For a
large repo where the relevant files aren't obvious, invoke `code-localisation`.

## 3. Language routing

Route by the repo's actual stack (`solution-profile.yaml:
tech_stack.primary_languages`), not by assumption. **Check availability first,
then language** — a language skill is a bonus, never a precondition:

- **A skill for the language is available** → invoke it (currently
  `csharp-implementation` for C#/.NET, `python-implementation` for Python —
  both ship in companion plugins and may not be installed). Those skills name
  the deeper specialists to compose with (`ef-core`, `aspire`,
  `ruff-recursive-fix`, `refactor`, …); treat each as a bonus. Do not assume the
  set is fixed — skills are added and may ship in separate plugins.
- **No skill for the language is available** (TypeScript / Go / Java / Rust /
  … , or the expected skill isn't installed) → work from the repo's own
  conventions: read neighbouring modules, honour the declared `tech_stack.*` and
  `lint_format_tools`, and apply the language's mainstream idioms and community
  style guide. Everything in this skill is language-neutral and still applies.
  **Say in the hand-off that you worked without a language skill.**

## 4. Cloud-native defaults

**Conditionally load `cloud-native-patterns`** when the change involves an
external boundary (HTTP / gRPC / message bus), a shared resource (DB / cache /
blob / queue), background work, startup/shutdown, or a new deployable. It is the
canonical source for Cloud Design Patterns (Retry, Circuit Breaker, Outbox,
Saga, Idempotency Key, Cache-Aside, Strangler Fig, Anti-Corruption Layer),
12-Factor readiness, resilience defaults, observability and HTTP API hygiene.

When it applies:

- Reach for a vetted Cloud Design Pattern instead of inventing one.
- Resilience comes from the ecosystem's established library (.NET:
  `Microsoft.Extensions.Http.Resilience` / Polly v8; Python: tenacity;
  equivalent elsewhere) — **never a hand-rolled retry loop**.
- Every outbound call gets a timeout + cancellation/abort signal. Use the
  platform's pooled HTTP client factory — never a fresh client per call.
- Honour 12-Factor: stateless processes, config from env / secret store,
  structured JSON logs to stdout, graceful `SIGTERM` shutdown, liveness +
  readiness endpoints (liveness must not depend on downstreams).
- For non-idempotent retried HTTP, accept an `Idempotency-Key`. For dual-write
  scenarios (DB + broker), use the Outbox pattern.
- Errors over HTTP are RFC 9457 Problem Details. Pagination on every unbounded
  query touched by user input.

## 5. Observability is part of "done"

Emit OpenTelemetry traces / metrics / logs via the language's OTel SDK and the
platform's structured-logging abstraction (.NET: `ILogger<T>` +
`ActivitySource`; Python: `structlog` / `python-json-logger` + OTLP exporter;
equivalent elsewhere). Propagate W3C `traceparent` on every outbound call. **No
PII or secrets in logs.**

## 6. Correctness details that get skipped

- **Language-idiomatic.** Match the conventions of the project's language and
  framework. Don't introduce a foreign style.
- **Selective data fetching.** Only request properties actually used in the
  result mapping.
- **Error handling.** Never swallow errors silently. Let exceptions propagate to
  the correct handler layer. Use structured logging at appropriate levels. Never
  return error strings as results.
- **No drive-by changes.** No opportunistic formatting or refactors outside the
  request scope unless they are tightly coupled to the change being made.

## 7. Documentation in the same change

When your code change makes a README, `docs/`, public XML/docstring, OpenAPI
spec, or instruction file (e.g. `.github/copilot-instructions.md`, `AGENTS.md`)
inaccurate or incomplete, **update it in the same iteration**. Search the repo
for docs that reference what you changed (symbol name, route, config key, CLI
flag).

If you cannot find the documentation that should describe this area and the
change is non-trivially user-visible, **ask the user where it lives** (external
wiki, Confluence, separate docs repo) before completing — don't silently let
docs drift. Creating *new* documentation files is opt-in: only when explicitly
requested, or when none exists for a public surface you are introducing.

If `documentation.platform` is not `in-repo`, you can't write there: put the doc
delta in the hand-off for a human to publish.

## 8. AI-integrated surfaces

For LLM prompts, agent definitions, RAG retrieval, tool-calling, MCP servers, or
prompt templates in code, invoke the `ai-prompt-engineering-safety-review` skill
before hand-off **if the project installs it** — it is not bundled with this
plugin. Without it, self-check against the OWASP LLM Top 10 (untrusted input
reaching a prompt, unvalidated model output reaching a sink, over-broad tool
grants) and surface any unaddressed item as a trade-off so `security-reviewer` can
pick it up.

## 9. Verification before hand-off

Two checks, both mandatory, both run with the repo's **own** commands
(`solution-profile.yaml: quality_gates` / `tech_stack.lint_format_tools`, else
what its CI already runs). Never invent a toolchain the repo doesn't use.

1. **Build, lint and format pass.** A hand-off that says "should build" is a
   gate failure waiting to happen.
2. **If you touched startup, verify it still starts.** A build proves the code
   compiles, not that the host boots. When the change touches DI registration,
   configuration binding, the host/app builder, middleware,
   migrations-on-startup, or the entry point, **start the app once and confirm it
   comes up** — the same check the Stage 7 smoke slot runs, done now while the
   cause is one task's diff instead of the whole change. Report the result. If
   you can't work out how to start it, research it (`read-repo-context` §9)
   rather than skipping the check silently. The ecosystem startup-discovery
   skills answer this when their companion plugin is installed.

Then walk the change through the Pre-PR review checklist from
`engineering-standards` (standards, security, edge cases, regressions, docs)
before writing the hand-off. **You do not review yourself** — that is the
`review-lead` agent's verdict; this is a self-check, not a review.

## 10. Write permissions

**Branch, commit and push freely; opening a PR needs approval.** Create the
feature branch, stage, commit and push without asking — work on a branch, never
directly on the default branch. **Opening a pull request requires the user's
explicit approval**: prepare the branch and the PR body, then ask. **Completing,
merging or closing a PR is never yours** — nor is force-pushing, rewriting
shared history, or deleting a shared branch.

For commit messages use `conventional-commit` + `git-commit`, honouring
`backlog.commit_convention` and `required_commit_trailers`.
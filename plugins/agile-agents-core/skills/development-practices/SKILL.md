---
name: development-practices
description: >-
  Author the smallest correct code change: implementation, cloud-native defaults,
  observability, documentation, verification and Git safety. Coding loads this
  with testing-practices for production changes. IaC belongs to infrastructure;
  independent diff review belongs to review-lead.
metadata:
  applies_to: all
---

# Development practices

Authors own implementation and its tests; pair with `testing-practices`.

## 1. Craft bias

- **Smallest change that fully solves it.** Extend the pattern already in this
  file/module before introducing a new one. Prefer: existing repo pattern >
  standard library / platform feature > already-installed dependency > new
  dependency. A new dependency, boundary, contract, or cloud service is *not
  yours to add* — report it in `Open questions for review` and stop (the
  orchestrator routes it to `architect`).
- Prefer readable code and deletion over speculative abstractions, configuration
  or extension points.
- **Refactors preserve observable behavior.** Establish test evidence before and
  after; separate any intentional contract change from the refactor.
- **Never simplify away correctness.** Input validation at trust boundaries,
  error handling that prevents data loss, authn/authz, secrets handling, and
  accessibility basics are non-negotiable regardless of how small the change is.

## 2. Research before proposing

Read the surrounding code first; never write from memory. If a newer framework
feature or library version is genuinely better, recommend it *with trade-offs*
rather than silently adopting it.

Verify consequential API/version facts using `read-repo-context` §9; label
anything unverified in the hand-off.

Read only the context needed for this task. `acquire-codebase-knowledge` is for
explicit onboarding, not an ordinary-task prerequisite. Use `code-localisation`
when the relevant files in a large repo are unclear.

## 3. Language routing

Use `read-repo-context` discovery before proposing gaps. Match available
descriptions/capabilities from local skills or installed external plugins to the
task, paths and declared stack/version (`tech_stack.*`). No historical names,
mandatory companion catalog or framework table. Optional depth is a bonus, not
a precondition. Native scoped instructions and existing CI/check commands count.

Without a match, read neighbouring modules, honour `lint_format_tools`, use repo
conventions and authoritative language documentation, and report the fallback.
Distinguish absent from ungranted before recommending setup.

## 4. Cloud-native defaults

Load `cloud-native-patterns` for external boundaries, shared resources,
background work, startup/shutdown or a new deployable. Apply its resilience,
12-Factor, idempotency, lifecycle and API contracts through the solution's
established implementation; do not add packages by default.

## 5. Observability is part of "done"

Use the solution's correlated traces, metrics and structured logs. Apply
`cloud-native-patterns`' propagation contract; SDK/exporter/sink selection belongs
to solution guidance. Report fallback to repo/docs. **No PII or secrets in logs.**

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
prompt templates, select applicable prompt-safety guidance by available description.
Without matching guidance, self-check against the OWASP LLM Top 10 (untrusted input
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
   rather than skipping the check silently. Use applicable startup-discovery
   capabilities from solution guidance when available.

### Pre-PR self-check

Before hand-off: confirm actual build/test/lint/format results; repo conventions
and accepted decisions; secrets, least privilege, input validation, authn/authz,
injection and dependency risks; edge/error cases; regression evidence; and docs
for changed setup, architecture and public surfaces. Explain every existing-test
change. **This is a self-check, not a review**: `review-lead` owns the verdict.

## 10. Write permissions

**Branch, commit and push freely; opening a PR needs approval.** Create the
feature branch, stage, commit and push without asking — work on a branch, never
directly on the default branch. **Opening a pull request requires the user's
explicit approval**: prepare the branch and the PR body, then ask. **Completing,
merging or closing a PR is never yours** — nor is force-pushing, rewriting
shared history, or deleting a shared branch.

### Git safety and conventions

Honour explicit user restrictions and stricter personal consent. Inspect status,
working and staged diffs; preserve unrelated edits and stage only the intended
paths/hunks. Never commit secrets, change Git config, bypass hooks or use a
destructive reset. A failed hook is repaired and retried as a new commit, not
amended into unrelated history.

Use `backlog.branch_naming`, `backlog.commit_convention`, `required_commit_trailers`
and `backlog.pr_link_pattern`. Derive the message from the staged diff; do not
impose Conventional Commits on another convention. When selected, use
`type(scope): summary`, with `!` / `BREAKING CHANGE:` for breaking changes.
Missing required conventions are gaps, not permission to invent them.
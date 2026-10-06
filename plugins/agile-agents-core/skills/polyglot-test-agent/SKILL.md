---
name: polyglot-test-agent
description: >-
  Cross-language testing fallback for the current author when no matching language testing skill is installed.
  Use for scoped test authoring, failure repair or coverage work using the repo's existing tools and conventions.
  Not a separate agent pipeline, a replacement for installed stack skills, or a review workflow.
applies_to: all
---

# Cross-language testing fallback

The current author carries out this workflow in place. The invoking `coding`
author owns production code and its tests and may fix production logic within
the task's scope. Do not self-delegate or launch another testing pipeline.
Reviewers use this as reference only, never as permission to write tests.

Reuse `testing-practices` for behaviour-focused cases, determinism, test doubles
and failure diagnosis (§§1–2, 5–6). Do not re-enter its framework-routing step
when it has already selected this fallback. If a matching language testing skill
is installed, use that skill directly instead; otherwise follow repo conventions
and report the missing deep capability. Neither path needs a new agent.

## 1. Discover the scoped repository conventions

Read the requested source, nearby tests, test manifests, config and CI commands.
Identify the existing framework, test locations, fixtures, assertion style and
build/test/lint/format commands before writing. Honour the profile's
`tech_stack.test_discipline` and `team_communication.code_language`. If the scope
or intended behaviour is unclear, ask rather than inventing it. Missing tooling
is a blocker to report, not permission to install a new dependency.

## 2. Choose behaviour cases

Map each changed behaviour to an observable assertion: the happy path, a boundary
that matters and a negative path that would catch a defect. Reuse existing
fixtures and parameterization patterns; prefer real objects and controlled
external dependencies. The optional [case checklist](unit-test-generation.prompt.md)
adds prompts for selecting cases, not another execution workflow.

## 3. Implement and run

Write the scoped tests and any in-scope production fix in the same task. Follow
`testing-practices` §2: never weaken assertions, delete or skip tests to get green.
If a test is wrong, prove it before changing it; if uncertain, stop and surface
the ambiguity. Escalate a fix requiring a new dependency, contract or design
decision instead of expanding scope.

Run the repo's build, targeted tests, full suite, lint and format checks.
Diagnose failures from evidence and rerun after repair. Do not substitute a
claimed result for an actual run.

## 4. Coverage and task hand-off

Use the repo's existing coverage command, honour `tech_stack.coverage_threshold`,
and inspect uncovered changed behaviour rather than inventing a percentage.
If coverage tooling is absent, report **not measured** and the cases exercised;
do not silently install a collector or claim a numeric result.

Return the invoking author's canonical `IMPLEMENTATION COMPLETE` task hand-off:
changed production/test files, behaviour → test mapping, exact commands and
results, coverage evidence or limitations, and any missing capability.
In `Existing tests modified`, justify every existing-test change: what the old
assertion claimed and why it was invalid. Pass the combined diff to independent
review through the existing caller's workflow; do not perform your own review.

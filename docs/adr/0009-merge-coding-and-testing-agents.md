# ADR 0009 — Give one task author ownership of implementation and its tests

- **Status:** Accepted
- **Date:** 2026-08
- **Deciders:** Harness maintainers (agent-roster consolidation)
- **Supersedes in part:** ADR 0003 (stage numbering only; the verification-gate decision stands), ADR 0006 (event-role inventory), ADR 0007 (capability-tier assignments)

## Context

Production behavior and its tests are developed together. Splitting those
activities between separate authors adds a hand-off and can leave a failing
test with no clear owner. At the same time, authors must not weaken assertions
to make their own work appear correct.

## Decision

The author responsible for a task's implementation also owns the tests that
verify that task. A separate deterministic gate and independent review remain
responsible for checking the result; existing tests may not be weakened without
an evidence-based justification.

## Consequences

- Implementation and test changes can be corrected together without an
  additional author hand-off.
- The author has responsibility for both the behavior and its verification,
  increasing the importance of independent checks and explicit accounting for
  changed assertions.
- Test guidance remains independently reusable from implementation guidance.

## Amendment (2026-11-12) — permit the run lead to author approved tasks

For an approved task, the run lead may author implementation and tests directly
or delegate the task to a specialist. This is a task-level author choice; it
does not change the requirement for independent review, deterministic checks,
or human approval boundaries.

## Alternatives considered

- **Keep implementation and test authors separate.** Rejected: it adds a
  hand-off and makes ownership of failures less clear.
- **Let the author own the work without independent checks.** Rejected: an
  author must not be the sole judge of its own assertions.
- **Allow the run lead only to coordinate.** Superseded by the amendment:
  direct authorship is useful for approved tasks when it fits the work.

## References

- ADR 0003 — deterministic verification before review
- ADR 0006 — run-level evidence
- ADR 0007 — advisory model-capability intent
- `plugins/agile-agents-core/skills/testing-practices/`
- `plugins/agile-agents-core/skills/test-bar-gate/`

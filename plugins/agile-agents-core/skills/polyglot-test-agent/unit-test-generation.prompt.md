---
description: 'Optional behaviour-case checklist for the current author using repository testing conventions'
---

# Unit test case checklist

Use alongside [the fallback workflow](SKILL.md), not as another pipeline.
`testing-practices` supplies the verification bar and the rule against weakening
tests; reuse the matching installed language testing skill for stack-specific
details. Otherwise work from the repo's existing tests, manifests and CI.
Do not recursively invoke the fallback or its caller.

For the requested scope:

- Identify the observable contract and its evidence before choosing assertions.
- Choose the happy path, meaningful boundaries, invalid inputs and error paths.
  Include state transitions or concurrency only when the behaviour requires them;
  do not cap negative cases to keep a positive/negative ratio.
- Reuse the repo's fixtures, naming and parameterization. Prefer real objects;
  isolate uncontrolled external dependencies rather than mocking internal logic.
- Explain what bug each case catches. Avoid assertions about implementation
  details, language features or the current output merely because it passes.
- Produce complete tests with the repo's imports and setup, no placeholders.

Run and report through the fallback workflow's existing task hand-off. Follow
the declared coverage policy, not a checklist-specific target. A red test is
evidence to diagnose, not a reason to change its expected result: an existing
assertion may change only after proving it invalid and justifying it in
`Existing tests modified`.

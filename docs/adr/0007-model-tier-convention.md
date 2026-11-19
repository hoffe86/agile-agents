# ADR 0007 — Keep model-capability intent separate from runtime model selection

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** Repository owner

## Context

The harness needs to express the reasoning capability preferred for classes of
work, but a preference is not proof of which model a runtime will select.
Treating descriptive metadata as executable configuration would create an
unsupported and potentially misleading control.

## Decision

Represent model-capability intent only as advisory metadata supported by the
target agent format. Keep actual model selection and authorization under the
runtime's documented controls; do not infer enforcement, model identity, or
quality from the advisory label.

## Consequences

- Maintainers can communicate intended capability without creating a custom
  model resolver.
- The metadata may not match the model actually selected, so runtime evidence
  is required for claims about execution.
- The representation is specific to the target runtime and must be revisited
  if that runtime's metadata contract changes.

## Alternatives considered

- **Treat advisory labels as executable selection policy.** Rejected: the
  metadata contract does not establish that behavior.
- **Remove capability intent entirely.** Rejected: it remains useful
  documentation when clearly separated from runtime controls.
- **Build a custom tier-to-model resolver.** Rejected: that would add a
  separate selection and authorization mechanism.

## References

- GitHub Copilot custom-agent configuration reference
- `.github/solution-profile.yaml`

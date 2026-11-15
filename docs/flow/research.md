# Research

Research is **read-only verification**, not design from scratch. Humans prepare
the concept (arc42, C4 or whatever `documentation.framework` declares) and any
accepted decision records before the run; Research checks the requirement fits.

## What happens

- `dev-lead` verifies the codebase, APIs and patterns the requirement touches.
- When scope warrants a new boundary, dependency or non-trivial trade-off, it
  delegates to `architect`, which returns `ARCHITECTURE DESIGN COMPLETE`.
- Every load-bearing external fact — a service, limit, quota, price or API shape
  — is either verified with a source or listed as an assumption with its impact.

## Gate

Research passes only when each decision is captured somewhere (an accepted ADR,
a design document or the verification sketch), a concrete interface contract
exists for tasks to reference, and NFRs and security posture are named.

Projects without ADRs are supported: "no ADR exists" is not a failure. A missing
*material* decision is a **decision gap** and goes to you at design approval;
agents never write the ADR themselves.

Next: [Plan and approvals](plan.md).

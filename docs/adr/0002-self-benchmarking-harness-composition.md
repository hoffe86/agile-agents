# ADR 0002 — Self-benchmarking harness composition (25 SWE-bench Verified + 10 ISD-custom tasks)

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** Wave 1+2 implementation of the autonomous-coding-agents improvement plan (H2)
- **Related research:** `docs/research/autonomous-coding-agents-2026.md` §6 (row H2)

## Context

You cannot improve what you do not measure. Wave 1+2 introduces three changes
(H1 localisation, H3 test-bar gate, H4 cost envelope) whose value can only be
quantified against a stable, repeatable benchmark. We need a self-benchmarking
harness that:

- runs in a few hours on a developer laptop (not a cluster),
- exercises the actual agent suite end-to-end (not just the LLM),
- mixes industry-comparable tasks with tasks that look like our real work
  (Mercedes Speech RFP, TeamPlay Agentic Bot, Bundeswehr news pipeline,
  Angio Voice Companion, etc. — see `.github/copilot-instructions.md`).

The candidate datasets are:

- **SWE-bench / SWE-bench-Lite / SWE-bench Verified** (Jimenez et al.,
  arXiv:2310.06770) — 300+ real GitHub issues with executable test suites.
  Verified is the human-curated subset (~500 tasks) where the underlying
  tests are known to be reliable.
- **HumanEval / MBPP** — small algorithmic tasks; do not exercise repo
  navigation or multi-file edits, so they don't measure what our agents
  actually do.
- **Custom internal tasks** — tasks drawn from our active project portfolio.

## Decision

The harness ships **two complementary task sets**:

1. **SWE-bench Verified subset of 25 tasks**, sampled to cover the difficulty
   distribution (small / medium / large patches) and the repo diversity of
   the parent set. 25 was chosen as the smallest sample that fits in a
   reasonable laptop budget (≈2–4h walltime, well under the H4 large-tier
   cost envelope) while still giving a meaningful pass-rate signal.
2. **10 ISD-representative custom tasks** drawn from real engagement patterns
   — Bicep IaC drift fixes, ASR pipeline bugs, AKS Helm chart upgrades,
   sovereign-cloud region constraints, etc. These cover dimensions SWE-bench
   does not — IaC, multi-language repos, regulatory constraints from
   `solution-profile.yaml: compliance_security`.

Both sets are versioned in-repo so historical runs remain comparable.

## Consequences

**Positive**
- Industry-comparable signal (the SWE-bench portion) plus
  ISD-representative signal (the custom portion).
- Small enough to run on every meaningful change to the agent suite.
- H1, H3, H4, H6 each get a measurable before/after.

**Negative**
- 25 tasks is a small sample — pass-rate confidence intervals are wide.
  Direction of change is reliable; absolute numbers are not.
- Custom-task curation is ongoing work; the 10 tasks need refresh as the
  engagement portfolio shifts.

## Alternatives considered

- **Full SWE-bench-Lite (300 tasks).** Rejected: ~30× the runtime and cost,
  not viable for tight iteration loops; runs would not happen frequently
  enough to actually shape decisions.
- **Custom tasks only.** Rejected: no industry comparability, no way to
  position against the published Agentless / SWE-agent / Aider numbers, no
  external validity.
- **SWE-bench Verified subset only.** Rejected: misses IaC, regulatory, and
  multi-language scenarios that dominate ISD work — exactly the dimensions
  where our suite must be strong.

## References

- `solution-profile.yaml` (will reference the harness once
  H2 task assets land; cost cap from `cost_envelope.tier=large` budgets the
  full run)
- `docs/research/autonomous-coding-agents-2026.md` §6 row H2; Stream D
- SWE-bench: Jimenez et al., *SWE-bench: Can Language Models Resolve
  Real-World GitHub Issues?* arXiv:2310.06770
- SWE-bench Verified: <https://www.swebench.com/verified.html>

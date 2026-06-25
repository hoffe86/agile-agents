# E1 — Magentic-One-style stall detection in supervisor

**ID:** E1
**Status:** scaffolded — not yet executed
**Owner:** TBD
**Depends on:** H2 baseline telemetry, H6 sentinel-block instrumentation

## 1. Hypothesis

The `dev-lead` supervisor can be made materially more robust by adding an explicit **stall counter** that triggers an outer-loop replan after N=2–3 failed retries within a single phase, mirroring Magentic-One's Task/Progress Ledger pattern. We believe stalls are common enough in real customer runs that handling them centrally beats relying on each author/reviewer to recover.

## 2. Source from whitepaper

> **E1** — *Magentic-One-style stall detection in supervisor: after N=2-3 failed retries within a phase, replan via outer loop* — Effort: Medium. Cited evidence: Magentic-One (Stream A); Cursor scaling experiments (Stream E §19). Open question: *"Does our pipeline hit stalls often enough to warrant the complexity? Need data from H2/H6 first."*
> — `docs/research/autonomous-coding-agents-2026.md` §6.2

Supporting context from §5.3: *"Magentic-One's dual-loop (Task Ledger outer + Progress Ledger inner) is a richer variant with explicit stall detection (after `stall_count > 2`, replan)."*

## 3. Proposed experiment

**Data to measure (during ≥30 real pipeline runs across ≥3 customer repos):**

| Metric | How to capture |
|---|---|
| Stalls per run (no progress for >1 phase iteration) | Sentinel-block timestamps; absence of `IMPLEMENTATION COMPLETE` etc. within phase budget |
| Retry events per phase | Count of repeated invocations of same author/reviewer for same phase |
| Recovery outcome per stall (self-recovered / human-rescued / abandoned) | Manual labelling of run logs |
| Wall-clock + token cost per stalled run vs healthy run | Telemetry from H2 |
| Phase distribution of stalls (architect / coding / testing / infra / review) | Sentinel parsing |

**Procedure:**
1. Run baseline (no stall detection) for 2 weeks across diverse tasks.
2. Tag each run as `clean | stall-recovered | stall-fatal`.
3. If `stall-rate ≥ 15 %` and `stall-fatal-rate ≥ 5 %`, build a minimal stall counter prototype in `dev-lead` and re-run the same task set.

**Success criteria (numeric):**
- ≥ 50 % reduction in `stall-fatal` runs after prototype, OR
- ≥ 30 % reduction in median time-to-recovery for stalled runs,
- with no regression > 10 % in token spend on healthy runs.

## 4. Decision criteria

| Evidence | Action |
|---|---|
| Stall rate < 5 % in baseline | Reject — promote to **C** (contrarian / not worth complexity) |
| Stall rate 5–15 %, but mostly self-recovered | Defer — keep in E, revisit at next FY |
| Stall rate ≥ 15 % AND prototype hits success criteria | Promote to **H** (adopt) — design dual-ledger in `dev-lead` |
| Prototype shows degraded healthy runs | Reject prototype design, redesign or drop |

## 5. Effort estimate

**Medium.** Instrumentation is small once H2/H6 land; the prototype itself is contained in `dev-lead.agent.md` plus a small ledger schema. Risk is in regression testing across customer repos.

## 6. Open questions

- Where exactly does the stall counter live — supervisor prompt state, or a side-channel YAML the supervisor reads/writes between turns?
- Should the replan invoke the `architect` author, or just re-prompt the same author with the failure context?
- How do we distinguish "model genuinely stuck" from "task underspecified" — does the latter need to bubble back to the human?
- Does Copilot CLI's session model support cleanly re-entering an outer loop, or does it require a fresh agent invocation?

## 7. References

- Fourney, A. et al. (2024). *Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks*. arXiv:2411.04468 — paper P-5 in §7.1.
- Microsoft Research — Magentic-One (Nov 2024) — https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/ — vendor V-4.
- Cursor scaling experiments — Stream E §19 (whitepaper bibliography entry).

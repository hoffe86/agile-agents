# E3 — Runtime file-restriction enforcement on reviewers

**ID:** E3
**Status:** scaffolded — not yet executed
**Owner:** TBD
**Depends on:** H6 telemetry (to detect existing read-only violations)

## 1. Hypothesis

The reviewer read-only contract is **prompt-only** today; Roo-Code already enforces file restrictions at the tool layer via `fileRestrictions`. We believe (a) frontier models occasionally violate prompt-only contracts under load, and (b) a runtime enforcement layer eliminates an entire failure class without adding meaningful operational complexity. We expect H6 telemetry to show ≥ 1 detectable violation per ~100 review runs, justifying the enforcement.

## 2. Source from whitepaper

> **E3** — *Runtime file-restriction enforcement on reviewers (Roo-Code-style fileRestrictions), replacing the prompt-only read-only contract* — Effort: Medium. Cited evidence: Stream B §Roo-Code. Open question: *"Have reviewers ever actually violated read-only in our usage? H6 makes this measurable."*
> — `docs/research/autonomous-coding-agents-2026.md` §6.2

Executive summary §1.2: *"Reviewer enforcement. The read-only contract is prompt-only; Roo-Code already enforces file restrictions at the tool layer; Continue ships CI-enforceable reviewer rules. Prompt-only contracts are routinely violated by current frontier models under load."*

## 3. Proposed experiment

**Phase 1 — measurement (passive, 4 weeks):**

| Metric | How |
|---|---|
| Reviewer write-attempt rate | Inspect tool-call audit logs for any `edit/create/write` tool invocation by an agent whose `agent.md` declares reviewer role |
| Reviewer write-success rate | Same, filtered to successful tool calls (i.e., file actually changed) |
| Distribution of attempted writes by file type / target | Categorise (test files, source, config, docs) |
| Self-reported intent in surrounding turns | Sample violations, classify as malicious / accidental / "fix obvious typo" |

**Phase 2 — enforcement prototype (only if Phase 1 shows ≥ 1 violation per 100 runs):**

- Wrap reviewer agents with a tool-call interceptor (Copilot CLI hook or post-tool-call validator) that rejects any `edit/create/write/delete` call.
- Re-run the same task pool; measure: (a) does the prototype block all write attempts? (b) does it cause reviewer agents to fail or loop?

**Success criteria:**
- Phase 1: violation rate quantified.
- Phase 2: 100 % of write attempts blocked; reviewer task-completion rate degrades by ≤ 5 %; no infinite-loop pathology.

## 4. Decision criteria

| Evidence | Action |
|---|---|
| Phase 1: 0 violations across ≥ 200 runs | Reject — promote to **C** (prompt-only contract is sufficient) |
| Phase 1: rare violations, all benign (e.g., touching scratch files) | Defer — document risk, keep prompt-only |
| Phase 1: any violation that would have shipped non-reviewed code, OR ≥ 1/100 violation rate | Promote to **H** — implement runtime enforcement |
| Phase 2: prototype causes > 5 % task failure | Redesign (e.g., return blocked-write as soft signal back to reviewer) |

## 5. Effort estimate

**Medium.** Phase 1 is light (telemetry only). Phase 2 needs a Copilot-CLI-compatible interception mechanism; the implementation pattern is well-established (Roo-Code's `fileRestrictions`) but the integration point in our stack must be designed.

## 6. Open questions

- What's the actual interception hook in Copilot CLI? Pre-tool-call middleware, agent-runner wrapper, or sandboxed execution context?
- Should reviewers be allowed to write to a scratch / "review-notes" directory by exception?
- How does enforcement interact with reviewer agents that legitimately need to *run* tests (which may write artifacts)?
- Is there a portable way to express the restriction in the agent.md frontmatter so it survives template distribution?

## 7. References

- Roo-Code — https://github.com/RooCodeInc/Roo-Code (23.9k★) — O-7 in §7.3, "closest skills-format match; runtime fileRestrictions".
- Continue — https://github.com/continuedev/continue (33k★) — O-6 in §7.3 (related: CI-enforceable reviewer rules; see also E4).
- Whitepaper §1.2 (executive summary), §6.2 (E3 row).

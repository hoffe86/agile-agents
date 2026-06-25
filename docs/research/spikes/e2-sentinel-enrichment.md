# E2 — Enrich sentinel-block schema with concerns / deviations / findings / follow-ups

**ID:** E2
**Status:** scaffolded — not yet executed
**Owner:** TBD
**Depends on:** H6 (sentinel-block instrumentation A/B harness)

## 1. Hypothesis

Today's sentinel blocks (`IMPLEMENTATION COMPLETE`, `REVIEW COMPLETE`, etc.) are essentially pass/fail signals. We believe enriching them with **structured "concerns / deviations / findings / follow-ups"** sections — Cursor-style handoff notes — will measurably improve downstream reviewer precision/recall without bloating context cost. The expected mechanism: reviewers spend fewer tokens re-discovering known issues and catch more of the issues the author already flagged.

## 2. Source from whitepaper

> **E2** — *Enrich sentinel-block schema to carry "concerns / deviations / findings / follow-ups" à la Cursor handoff notes* — Effort: Small. Cited evidence: Stream E §19 (Cursor scaling); §16 (Devin uses richer context). Open question: *"Does richer sentinel content materially improve reviewer quality? A/B test after H6 makes data available."*
> — `docs/research/autonomous-coding-agents-2026.md` §6.2

Supporting context from §5.3: *"Cursor's worker handoff notes carry 'concerns, deviations, findings, thoughts, and feedback' — our sentinel blocks are mostly pass/fail signals."*

## 3. Proposed experiment

**Variant A (control):** existing minimal sentinel schema.
**Variant B (treatment):** sentinel adds four optional structured fields:
- `concerns:` (list) — things the author thinks might be wrong
- `deviations:` (list) — places where implementation differs from architecture or spec
- `findings:` (list) — incidental issues discovered (out of scope, but logged)
- `follow-ups:` (list) — work explicitly deferred

**Data to measure (≥40 task runs per variant, same task pool):**

| Metric | How |
|---|---|
| Reviewer-found issues per PR | Count from review-agent sentinel output |
| Reviewer false-positive rate | Sample 20 PRs/variant, manual label |
| Reviewer token spend per PR | Telemetry |
| Author→reviewer overlap (issues author flagged that reviewer missed) | Cross-reference concerns vs reviewer findings |
| Time-to-merge | Wall-clock |

**Success criteria:**
- Variant B raises reviewer recall (real-issues-found / real-issues-present in seeded bug set) by **≥ 20 %**, OR
- Variant B reduces reviewer token spend by **≥ 15 %** with no recall regression,
- AND author-side cost of producing the richer sentinel rises by **≤ 10 %**.

## 4. Decision criteria

| Evidence | Action |
|---|---|
| Variant B meets either success threshold | Promote to **H** — update sentinel schema canon |
| Variant B equal to control on both metrics | Reject — promote to **C** (writing notes ≠ better notes) |
| Variant B improves recall but blows author cost | Iterate — try shorter required schema; re-spike |
| Inconclusive (n too small) | Extend run, do not decide |

## 5. Effort estimate

**Small.** Schema change is a one-paragraph addition to the hand-off canon and the relevant author skills. The A/B harness and seeded-bug evaluation set are the real cost — but H6 already produces them.

## 6. Open questions

- Should the four fields be required or optional? Required risks low-quality "N/A" stuffing; optional risks adoption.
- Is there a max-size budget per field to prevent context bloat?
- Do reviewers need new prompting to actually *use* the new fields, or does putting them in the prompt suffice?
- How do we keep this from drifting into a free-form essay format that defeats the structured-handoff purpose?

## 7. References

- Cursor scaling experiments — Stream E §19 (whitepaper bibliography).
- Devin (Cognition) — Stream E §16; §13.4 — "writer→clean-context-reviewer→autofix loop".
- Cognition — *Don't Build Multi-Agents* (2025) — Principle 2: "actions carry implicit decisions" (rationale for richer hand-offs).

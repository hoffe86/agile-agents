# E4 — CI-enforceable reviewer rules (YAML rubrics)

**ID:** E4
**Status:** scaffolded — not yet executed
**Owner:** TBD
**Depends on:** customer-CI access for ≥ 2 representative repos

## 1. Hypothesis

Encoding reviewer rubrics as **YAML rules that CI can re-evaluate** (à la Continue) gives customers a deterministic, auditable second-pass review independent of the agent's stochastic output. We believe this is the single most defensible governance feature for regulated-customer engagements (Bundeswehr, automotive), and that customer CI infrastructure usually does expose suitable hooks.

## 2. Source from whitepaper

> **E4** — *CI-enforceable reviewer rules à la Continue: encode review rubrics as YAML so CI can re-evaluate* — Effort: Medium. Cited evidence: Stream B §Continue. Open question: *"Does customer CI infrastructure usually expose hooks to run extra rule checks? Customer-by-customer answer."*
> — `docs/research/autonomous-coding-agents-2026.md` §6.2

Supporting context from §5.6: *"Continue ships CI-enforceable reviewer rules — the most novel approach in the OSS landscape, encoding rules as YAML that CI can re-evaluate."*

## 3. Proposed experiment

**Step 1 — translate one reviewer to YAML rubric:**
Pick the `code-review-checklist` skill. Express its 8–12 most-checked items as a YAML schema, e.g.:

```yaml
rules:
  - id: no-secrets-in-source
    pattern: "(api_key|password|secret)\\s*=\\s*['\"]"
    severity: error
  - id: error-handling-required
    requires: "try/except OR Result<>" in any new public function
    severity: warning
```

**Step 2 — build minimal evaluator** that runs the YAML rules against a PR diff and emits a structured report (pass/fail per rule + matched lines).

**Step 3 — pilot in 2 customer repos** (one with GitHub Actions, one with Azure DevOps Pipelines). Measure:

| Metric | How |
|---|---|
| % of agent-reviewer findings reproducible by YAML rules | Cross-reference 30 PRs |
| Rule false-positive rate | Manual review of CI alerts |
| CI runtime overhead | Pipeline timing |
| Customer-side install friction | Onboarding journal |
| Rules trivially expressible in YAML vs requiring agent reasoning | Categorise the 12 rubric items |

**Success criteria:**
- ≥ 60 % of deterministic rubric checks expressible as YAML rules,
- false-positive rate ≤ 10 %,
- CI overhead < 30 s per PR,
- both pilot customers' CI accept the integration without bespoke infra changes.

## 4. Decision criteria

| Evidence | Action |
|---|---|
| All four success criteria hit, in both pilots | Promote to **H** — add `cicd-pipeline-implementation` skill variant; ship default rubric YAML alongside template |
| Hits in 1 of 2 pilots, infra-blocked in the other | Promote to **H** for compatible customers, document caveat |
| < 40 % rules expressible in YAML | Reject — agent reasoning is the value-add; promote to **C** |
| Customer CI requires bespoke connectors > 2 days each | Defer — too high friction for ISD delivery model |

## 5. Effort estimate

**Medium.** YAML schema + evaluator is maybe a week of focused work. The pilot integration into customer CI is the variable cost — depends on whether their pipeline allows arbitrary action/task plug-ins.

## 6. Open questions

- Where does the YAML live — in the customer repo (`.github/review-rules.yaml`) or in our template?
- How do we keep the YAML in sync with the agent's reviewer skill (single source of truth vs duplication)?
- Should the evaluator be a binary, a Docker image, or a GitHub Action / Azure DevOps Task — and which formats do our top customers prefer?
- Do we need a Continue-compatibility mode so customers can reuse Continue's existing rule corpus?

## 7. References

- Continue — https://github.com/continuedev/continue (33k★) — O-6 in §7.3, "CI-enforceable rules pattern".
- Whitepaper §5.6 (Quality gates), §6.2 (E4 row).
- (Customer-side, customer-by-customer): GitHub Actions docs, Azure DevOps Pipelines extension SDK.

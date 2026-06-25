# E6 — Mid-tier fine-tune for `coding` and reviewer roles (go / no-go decision)

**ID:** E6
**Status:** scaffolded — not yet executed — **decision-only spike**
**Owner:** TBD
**Depends on:** H2 baseline benchmarks, H4 cost-tracking telemetry

## 1. Hypothesis

Shopify reported a fine-tuned 32 B model running **2.2× faster and 68 % cheaper** than the frontier model on Flow generation. The hypothesis under test is whether a comparable ROI exists for our **general-purpose `coding` and reviewer agents**. Our prior — based on the broader fine-tune-vs-prompt literature — is that **prompting + tool-use wins for general code generation**, and Shopify's win came from a *narrow, well-bounded, high-volume* DSL task. We therefore expect the answer to be **no-go for the general `coding` agent**, with a possible narrow exception for one specific reviewer if its task surface turns out to be small and stable.

## 2. Source from whitepaper

> **E6** — *Fine-tune mid-tier model for `coding` and reviewer roles following Shopify's recipe* — Effort: Large. Cited evidence: Stream E §21 (2.2× faster, 68 % cheaper). Open question: *"Justified only after H2 baseline + H4 cost-tracking show it pays off."*
> — `docs/research/autonomous-coding-agents-2026.md` §6.2

Supporting context from §5.11: *"Shopify's evidence is the long-term signal: a fine-tuned 32B model was 2.2× faster and 68 % cheaper than the frontier model at the same task."*

## 3. Proposed experiment (decision-only — no training run unless gate passes)

This spike is a **structured go / no-go evaluation**, not a fine-tune attempt. Sequence:

**Gate 1 — Volume.**
- Measure (from H4 telemetry): tokens consumed by `coding` and reviewer roles per month, per customer.
- Pass if: any single role exceeds **≥ 50 M tokens/month sustained for ≥ 3 months**. Below this, fine-tune amortisation period exceeds typical engagement length.

**Gate 2 — Task surface stability.**
- Sample 200 invocations of the candidate role; categorise by task type, language, framework.
- Pass if: top 10 task categories cover **≥ 80 %** of invocations and have remained stable across the measurement window. Highly variable surfaces (i.e., our typical multi-customer reality) fail this gate.

**Gate 3 — Quality headroom on cheaper model.**
- Run baseline tasks on the candidate mid-tier model (e.g., GPT-4.1-mini, Claude Haiku, Llama-3.1-70B) **with our existing skills/prompts only — no fine-tune yet.**
- Pass if: degradation vs frontier is **≥ 30 % on quality-relevant metric** (otherwise just switch to the cheaper model and skip fine-tuning entirely — that's a much cheaper win), AND **≤ 60 %** (otherwise fine-tune unlikely to close the gap).

**Gate 4 — Training data availability.**
- Audit: do we have ≥ 5 000 high-quality input/output pairs for the candidate role from real runs, with permission to use them?
- Pass if: yes, with customer IP cleared and PII scrubbed. ISD multi-customer constraints make this often the hardest gate.

**Decision rule:** all four gates must pass for go. Failing any one gate → no-go (or revisit when conditions change).

## 4. Decision criteria

**Likely outcome — current evidence points to no-go for the general `coding` agent:**
- Our `coding` agent's task surface is *deliberately broad* (any customer, any stack) — likely to fail Gate 2.
- ISD engagements are typically 3–9 months; sustained 50 M tokens/month per single tenant is rare — likely to fail Gate 1.
- Customer IP rules generally prohibit cross-tenant training data aggregation — likely to fail Gate 4.

**Possible exception — narrow reviewer role:**
A single reviewer with a stable rubric (e.g., `security-review`, `architecture-review`) operated as a *shared* (non-customer-specific) capability across many engagements *could* hit Gates 1+2+4 over time. Worth re-evaluating annually.

| Evidence path | Action |
|---|---|
| Any gate fails | **No-go.** Document; revisit in 12 months. Promote spike to **C** (rejected for now). |
| All gates pass for one specific role | **Go for that role only.** Promote to **H** with a scoped fine-tune project (separate large-effort initiative; this spike does not own the implementation). |
| Gates 1+2+3 pass but Gate 4 fails on data | **Conditional no-go.** Open a follow-up data-collection initiative; do not start training. |

## 5. Effort estimate

**Large** (if fine-tune proceeds — model selection, training infra, eval harness, productionisation, ongoing retraining, governance). The decision spike itself is **small** — the four gates can be evaluated from H2/H4 outputs in days.

## 6. Open questions

- What's our internal baseline for "quality-relevant metric" — SWE-bench-like pass-rate, reviewer-found-issues recall, or customer-acceptance score?
- Which mid-tier model would we fine-tune? Open-weights (Llama, Qwen) vs hosted (Azure OpenAI fine-tune)? Compliance posture differs significantly.
- For Gate 4: can we negotiate a "may use for model improvement" clause in standard ISD MSAs going forward?
- Is there a hybrid path — *adapter/LoRA per customer* for high-volume engagements — that side-steps the multi-tenant data problem?
- Does the Shopify recipe actually generalise outside DSL generation? The original blog post is the only public data point.

## 7. References

- Shopify Engineering — *Fine-tuning an agent: Shopify Flow* (Apr 2026) — https://shopify.engineering/fine-tuning-agent-shopify-flow — entry 78 in §7.5.
- Whitepaper §5.11 (Cost / token budget), §6.2 (E6 row).
- Anthropic — multi-agent research post (cost economics: ~15× chat token cost) — referenced §5.11.
- (For background on fine-tune-vs-prompt trade-offs in general code generation): broader literature consensus, see §7.1 academic bibliography for related pre-2026 work.

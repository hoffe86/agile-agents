# Model preferences — consumer-owned setup

## Manual native setup

This is a **proposal-only** procedure for `bootstrapper` and the profile interview,
not a runtime tier resolver. Before proposing model setup:

1. Read the consumer's `cost_envelope.model_tiers`, `ai_copilot.approved_models`,
   and the installed agents' `metadata.model_tier`. Propose only choices from the
   matching profile tier that are also in the approved list; do not infer new IDs
   from the historical table below. A legacy scalar is one advisory choice.
2. Preserve explicit user choices and per-agent overrides. Show a proposal per
   agent with its tier, map-derived choices, and any user-reported existing choice;
   do not treat the map as permission to replace it. Ask before any change.
   Missing or empty map (or no entry for that tier) → leave settings untouched,
   not force inheritance or clear overrides.
3. The user explicitly approves each choice and configures it manually through
   the native **`/subagents` UI**, selecting the installed agent and a preferred
   model. The bootstrapper must never write user/global configuration or apply
   settings implicitly; plugin-install approval is not model-setup approval.
   Do not generate settings files, hardcode native config keys, or pin shipped
   agents with `model` / `models`. Never set a task's `model` from the profile.
4. If a proposed model is unavailable in the user's UI, report it and let the user
   choose; do not silently substitute another model, even from the approved list.
   Do not assume availability from an ID or test it with a live model call.
5. Report choices as **proposed**, **user-confirmed configured**, **skipped**, or
   **unavailable** in the bootstrap summary. User confirmation is not execution
   evidence; do not claim which model ran. Skipping setup does not block the six
   required profile fields or change any existing runtime settings.

## Preference is not governance

Profile list order records advisory user choices, **not a native ordered-fallback
guarantee**. The native UI's documented per-agent model setting is scalar; do not
translate a profile list into a claimed native fallback chain.

Native preferred fallback may leave `ai_copilot.approved_models` (for example, by
using the session model). CI checks only static map/approved-list consistency,
not runtime model selection or authorization. Neither the map nor this manual
setup enforces governance, suitability, savings, or a cost budget.
If approved-only execution is required, report that unmet governance requirement
to the user; do not present preferred setup as enforcement.

Exact-version syntax is not safely confirmed: the official command reference
documents `models` / `modelPolicy`, while the official 1.0.83 changelog describes
`model` / `model-policy`. Use the native UI, not a copied settings snippet.
Required-policy and Auto interactions remain **unverified on CLI 1.0.98**;
this guidance makes no required-policy guarantee and has not exercised them.
Do not change a user's existing policy or Auto choice to make a proposal fit.

Sources (consulted 2026-10-15; documentation, not runtime verification):
- [CLI command reference — custom agent frontmatter](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#custom-agent-frontmatter-fields)
- [CLI configuration reference — user settings and `/subagents`](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference#configuration-file-settings)
- [Official CLI changelog — 1.0.83](https://github.com/github/copilot-cli/blob/main/changelog.md#1083)

## Historical recommendations (2026-Q2)

These are historical 2026-Q2 recommendations, not executable defaults or current
model-suitability evidence. Agents record advisory `metadata.model_tier` in Copilot
frontmatter; this does not define a cross-harness contract. Confirm availability,
policy approval, and suitability before deliberately configuring a runtime model.

| Tier  | Anthropic           | OpenAI / Azure OpenAI | Notes                                                                       |
|-------|---------------------|-----------------------|-----------------------------------------------------------------------------|
| heavy | claude-opus-4.7     | gpt-5.4               | Planning, architecture & reviewers — explainability premium, judgement-heavy work. |
| mid   | claude-sonnet-4.6   | gpt-5-mini            | Day-to-day authors (coding, testing, infrastructure) — cost-quality sweet spot. |
| light | claude-haiku-4.5    | gpt-4.1               | Mechanical loops and doc-only tasks, subject to task evidence; not planning. |

The current [ADR 0007](../../../../../docs/adr/0007-model-tier-convention.md)
assignment for `dev-lead` is `heavy`: planning/decomposition, acceptance coverage,
risk sequencing, and gate judgement require deep reasoning. The roster has 0 light,
4 mid, and 11 heavy agents; `light` remains supported. This advisory policy does not
select a runtime model or validate the dated model recommendations above.

> **Re-baseline quarterly.** Re-evaluate these dated picks when models or task evidence
> change. `solution-profile.yaml: cost_envelope.model_tiers{}` may record preferences,
> but no runtime code consumes that map. Use the manual setup above, preserving user
> choices. Neither these recommendations nor the annotation automatically enforces
> `ai_copilot.approved_models`.

Profile tier values may be ordered nonempty lists of model IDs or legacy single
strings. Order is advisory, not automatic fallback. Use only `heavy`, `mid`, and
`light`, with no duplicate model IDs; each listed ID must appear in the profile's
`ai_copilot.approved_models`. The marketplace's existing checker validates this
static consistency in its root profile and generic shipped template, not the
runtime's model choice. Project-specific preferences belong in the project's
profile, never in the shipped template or these historical recommendations.

# Acceptance criteria — task-06

1. **Workflow lints** — `actionlint` (or equivalent) on `.github/workflows/deploy-prod.yml`
   reports zero errors.
2. **OIDC permissions correct** — workflow has top-level (or job-level) `permissions:` block
   with `id-token: write` and `contents: read` and no other write permissions.
3. **No secrets used for Azure auth** — `secrets.AZURE_CLIENT_ID` / similar do **not** appear;
   `vars.AZURE_CLIENT_ID`, `vars.AZURE_TENANT_ID`, `vars.AZURE_SUBSCRIPTION_ID` do.
4. **Concurrency configured** — workflow has a `concurrency:` key with `group:` referencing
   the workflow + ref, and `cancel-in-progress: false` (so deploys queue, not cancel).
5. **Actions SHA-pinned** — every `uses:` line for a third-party action is pinned to a full
   40-character commit SHA (a comment with the human-readable version is allowed and
   encouraged).

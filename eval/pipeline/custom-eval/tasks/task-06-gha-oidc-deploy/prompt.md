# Task 06 — Add a GitHub Actions workflow with OIDC deploy to Azure

## User story

As DevOps lead, I need a GitHub Actions workflow that builds, tests, and deploys our
ASP.NET Core service to an Azure Web App on every push to `main`, using **OIDC federated
credentials** (no long-lived secrets in the repo).

## Context

- Repo already contains `src/Web` (the ASP.NET project) and `tests/Web.Tests`.
- An Azure Web App and federated-identity app registration already exist (the `tenant-id`,
  `subscription-id`, `client-id` will be supplied as repo variables, not secrets).
- The Web App lives in resource group `rg-orders-prod` and is named `app-orders-prod`.

## Requested deliverable

A workflow at `.github/workflows/deploy-prod.yml` that:

1. Triggers on `push` to `main` and on `workflow_dispatch`.
2. Uses concurrency control so two pushes don't deploy in parallel.
3. Has three jobs: `build-test`, `deploy` (depends on `build-test`), and the right
   `permissions:` block for OIDC (`id-token: write`, `contents: read`).
4. Authenticates with `azure/login@v2` using the OIDC client-id / tenant-id / subscription-id
   from `vars`, no secrets.
5. Deploys with `azure/webapps-deploy@v3` to `app-orders-prod` in `rg-orders-prod`.
6. Pins all third-party actions to a full commit SHA (not a tag) for supply-chain hygiene.

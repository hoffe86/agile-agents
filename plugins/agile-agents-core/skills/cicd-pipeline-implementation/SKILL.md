---
name: cicd-pipeline-implementation
description: Implement CI/CD pipelines for infrastructure and application code using GitHub Actions or Azure Pipelines (YAML). Covers build, test, security scanning, container image build/push, IaC plan/apply gating, environment promotion, and OIDC-based passwordless auth to Azure. USE FOR any request to write, add, or modify files under `.github/workflows/`, `azure-pipelines.yml`, `.azuredevops/`, or any "set up CI", "add a pipeline", "deploy on merge" task. Triggered by "GitHub Actions", "Azure Pipelines", "ADO pipeline", "workflow", "OIDC", "federated credential".
applies_to: github-actions, azure-pipelines
---

# CI/CD Pipeline Implementation

You are authoring or modifying CI/CD pipelines.

## 1. Pick the platform

- **GitHub Actions** when the repo lives on GitHub. Files: `.github/workflows/*.yml`.
- **Azure Pipelines** when the repo lives in Azure DevOps. Files: `azure-pipelines.yml` (root) or `.azuredevops/pipelines/*.yml`.
- If both exist, the PR target / deployment target dictates which to extend; do not duplicate the same pipeline across platforms unnecessarily.

For NuGet trusted publishing (OIDC keyless publish to nuget.org), use **`nuget-trusted-publishing`** plugin skill.

## 2. Common conventions (both platforms)

- **One workflow per concern**: `ci.yml` (build+test on PR), `cd-infra.yml` (IaC plan/apply), `cd-app.yml` (build image + deploy), `pr-validation.yml`, `release.yml`.
- **Pin third-party actions/tasks to a commit SHA** (or for Azure Pipelines, a fixed task version) — never `@main` / `@v*` tags from untrusted publishers. `actions/*` and `azure/*` may use full version tags.
- **Permissions: least privilege.** GitHub Actions: top-level `permissions: {}`, then escalate per-job. Azure Pipelines: scope `AZURE_CREDENTIALS` / service connections to the minimum subscription/RG.
- **OIDC > stored secrets.** For Azure auth: federated credentials (`azure/login@v2` with `client-id`/`tenant-id`/`subscription-id`, no client secret). Configure the federated credential on a User-Assigned Managed Identity tied to the repo+ref/environment.
- **Concurrency control.** GitHub: `concurrency: { group: ..., cancel-in-progress: true }` for PR builds; `cancel-in-progress: false` for deploys. Azure Pipelines: `lockBehavior: sequential` on environments.
- **Matrix builds** when targeting multiple OS / runtime versions; use `fail-fast: false` so one failure doesn't kill the others.
- **Caching:** `actions/cache@v4` (or `Cache@2` task) for package managers (`npm`, `nuget`, `pip`, `gradle`); cache restore failures must not fail the build.
- **Reusable workflows** (GH `workflow_call` / ADO `template:`) for shared steps; don't copy-paste 50 lines across files.
- **Container images** push to `solution-profile.yaml: cicd.artifact_registry` when set (`acr` / `ghcr` / `docker-hub` / `jfrog` / `nuget-org`). Don't introduce a second registry because a sample used one — if the profile is empty, ask rather than pick.
- **Secrets** go in GitHub Environments / ADO Variable Groups linked to Key Vault. Never `echo $SECRET` — pipelines mask but file artifacts and external services don't.
- **Status checks required** on `main` / `release/*` branches; deploys gated on `environment:` with required reviewers.

## 3. CI conventions (build/test on PR)

- Triggers: `pull_request` on `main`/`release/*` + `push` on feature branches that the team works on.
- Steps in order: checkout (fetch-depth: 0 if you need git history) → setup runtime → restore cache → restore deps → build → test → upload artifacts → upload coverage.
- **Fail loud on warnings** for new projects (`-warnaserror` for .NET, strict mode for type checkers).
- **Test results published**: `actions/upload-artifact` + `dorny/test-reporter` (GH) or `PublishTestResults@2` (ADO).

## 4. CD conventions for IaC (Bicep / Terraform)

Two-stage flow: **Plan** (always) → **Apply** (gated on environment + manual approval for prod).

For **Terraform**:

```
- terraform fmt -check
- terraform init -backend-config=...     # backend per environment
- terraform validate
- terraform plan -out tfplan -var-file=envs/<env>.tfvars
- (gate) require approval if env == prod
- terraform apply -auto-approve tfplan
```

For **Bicep**:

```
- bicep build main.bicep
- az deployment <scope> what-if --template-file ... --parameters ...
- (gate) require approval if env == prod
- az deployment <scope> create --template-file ... --parameters ...
```

Persist plan output (`tfplan`, what-if JSON) as an artifact attached to the deployment.

## 5. CD conventions for application code

- **Build container** with multi-stage Dockerfile (use **`multi-stage-dockerfile`** vendored skill for guidance).
- **Push to ACR** using `az acr login` via OIDC, or build directly in ACR with `az acr build`.
- **Tag strategy:** `<git-sha>` is canonical; add `<branch>-latest`, `<semver>` on releases.
- **Deploy** by updating the Helm release / Kustomize overlay / `az containerapp update --image ...`.
- **Smoke test** post-deploy (curl health endpoint) before marking the job successful.
- **Rollback path** documented in the workflow's `README` or a comment header.

## 6. Security scanning to add by default

| Stage | Tool | Configured how |
|---|---|---|
| SAST | CodeQL (GH Actions: `github/codeql-action/*`) | `.github/workflows/codeql.yml` |
| Dependencies | Dependabot (config in `.github/dependabot.yml`) | Already on by default in many orgs |
| Secrets | Gitleaks / GitHub secret scanning | Push-protection enabled at repo level |
| IaC | `tfsec` / `checkov` / PSRule for Bicep | Run in PR; fail on high severity |
| Containers | `trivy image` against built image | Block on critical vulnerabilities |

For SAST orchestration, the **`codeql`** vendored skill provides workflow templates.

## 7. Validate before handing off

- **Lint locally:**
  - `actionlint` for GitHub Actions workflows.
  - `az pipelines runs list` is not validation; use ADO's built-in YAML editor "Validate" action or `az pipelines run --preview-only`.
- **Test the workflow on a feature branch** before merging to `main` — never trust a YAML pipeline file you haven't seen run green.

## 8. Hand off

```
PIPELINE IMPLEMENTATION COMPLETE
- Platform: GitHub Actions | Azure Pipelines
- New/changed workflows: <list>
- Triggers: <list>
- Auth method: OIDC federated identity (no stored client secrets) | service connection
- Approvals: <which environments>
- Open items for review: <if any>
```

## 9. What you do NOT do

- Don't add long-lived service principal secrets — surface a request to set up OIDC federated credentials instead.
- Don't deploy infra changes from CD without a Plan/what-if step the human can review.
- Don't disable required status checks to "unblock" a release.
- Don't commit (the orchestrator decides timing).

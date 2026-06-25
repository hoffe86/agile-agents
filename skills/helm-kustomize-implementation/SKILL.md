---
name: helm-kustomize-implementation
description: Implement Kubernetes deployments via raw manifests, Helm charts, or Kustomize overlays — with AKS in mind. Covers Deployment/Service/Ingress/HPA/PDB/NetworkPolicy authoring, Helm chart structure, Kustomize bases & overlays, and AKS-specific patterns (workload identity, Azure CNI, KEDA). USE FOR any request to write, add, or modify `.yaml` Kubernetes manifests, Helm charts (`Chart.yaml`, `values.yaml`, `templates/*`), Kustomize files (`kustomization.yaml`, overlays), or AKS workload definitions. Triggered by "Helm", "Kustomize", "K8s manifest", "Kubernetes deployment", "AKS", "Ingress", "HelmRelease".
---

# Helm / Kustomize / Kubernetes Implementation

You are authoring or modifying Kubernetes workload definitions.

## 1. Understand the existing state first

- Decide which packaging is in use:
  - **Raw manifests** (`*.yaml` under `k8s/` or `manifests/`)
  - **Helm chart** (`Chart.yaml` + `templates/` + `values.yaml`)
  - **Kustomize** (`kustomization.yaml` with bases + overlays)
- If targeting **AKS**, read any related Bicep/Terraform to understand: cluster networking (kubenet vs Azure CNI vs Azure CNI Overlay), workload identity setup, ingress controller (AGIC, NGINX, Application Gateway for Containers), node pools.
- Check the in-cluster GitOps tool if present (Flux, ArgoCD) — manifests must conform to its expectations.

For AKS provisioning concerns (cluster creation, node pools, networking), use the **`azure-kubernetes`** plugin skill or **`azure-aks`** MCP tool. This skill is for **workload definitions**, not cluster provisioning.

## 2. Conventions for raw manifests

- **`apiVersion`** is current and matches the cluster (`apps/v1`, `networking.k8s.io/v1`, `autoscaling/v2`).
- **Every workload has:**
  - Resource `requests` and `limits` (CPU + memory).
  - `livenessProbe` and `readinessProbe` (and `startupProbe` for slow starters).
  - `securityContext`: `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`.
  - `imagePullPolicy: IfNotPresent` (or `Always` for `:latest` — but never use `:latest` in prod).
  - Pinned image digests in production overlays.
- **PodDisruptionBudget** for every Deployment with replicas ≥ 2.
- **HorizontalPodAutoscaler** when traffic is variable; KEDA for event-driven.
- **NetworkPolicy** by default — deny-all egress, then explicitly allow what's needed.
- **No `hostNetwork`, `hostPID`, `hostIPC`, `privileged: true`** unless absolutely required and called out.
- **Labels**: `app.kubernetes.io/name`, `app.kubernetes.io/instance`, `app.kubernetes.io/version`, `app.kubernetes.io/component`, `app.kubernetes.io/part-of`, `app.kubernetes.io/managed-by`.

## 3. Conventions for Helm charts

- **Layout:** `Chart.yaml`, `values.yaml`, `values.schema.json` (highly recommended), `templates/`, `templates/_helpers.tpl`, `templates/NOTES.txt`, `crds/` for CRDs.
- **Bump `Chart.yaml: version`** on every chart change (semver). Bump `appVersion` when the underlying app version changes.
- **`values.schema.json`** validates inputs — write it; don't rely on documentation alone.
- **Templating:** use `include` + named templates from `_helpers.tpl` for fullname / labels / selectors. Don't repeat label blocks across templates.
- **No business logic in templates** — keep them declarative; push computation into `values.yaml` or helpers.
- **Lint and template-render before handing off:**

  ```powershell
  helm lint ./chart
  $rendered = Join-Path ([System.IO.Path]::GetTempPath()) 'rendered.yaml'
  helm template release-name ./chart --values values-prod.yaml | kubectl --dry-run=server apply -f -
  helm template release-name ./chart --values values-prod.yaml | Out-File -Encoding utf8 $rendered
  ```

## 4. Conventions for Kustomize

- **`base/`** contains the canonical resources; never environment-specific.
- **`overlays/<env>/`** apply patches — prefer **strategic-merge patches** for shape changes, **JSON 6902** for surgical edits.
- **`namespace`, `commonLabels`, `commonAnnotations`** set in `kustomization.yaml`.
- Use `configMapGenerator` / `secretGenerator` (with `behavior: merge`) for env-specific values; never check secret values into git — reference Key Vault via Secrets Store CSI Driver / External Secrets Operator.
- **Validate with:**

  ```powershell
  kustomize build overlays/prod | kubectl --dry-run=server apply -f -
  ```

## 5. AKS-specific patterns

- **Workload Identity** (federated credential to a User-Assigned Managed Identity) — annotate ServiceAccount `azure.workload.identity/client-id`, label pod `azure.workload.identity/use: "true"`. Don't use AAD Pod Identity (deprecated).
- **Azure CNI Overlay** is the default networking choice; ensure CIDR blocks don't overlap with VNets.
- **Image source: Azure Container Registry** with managed-identity pull (no `imagePullSecrets` for ACR when using AKS-ACR integration).
- **Ingress: Application Gateway for Containers** (AGC) is preferred for new clusters; AGIC and NGINX are still valid.
- **Logs/metrics**: Container Insights enabled at cluster level; ensure pod labels propagate so they're queryable.

## 6. Validate before handing off

Run all of:

```powershell
# Syntax + schema
kubectl apply --dry-run=client -f <files>
kubectl apply --dry-run=server -f <files>     # round-trips through API server validation

# Helm
helm lint ./chart
helm template ./chart | Out-File -Encoding utf8 (Join-Path ([System.IO.Path]::GetTempPath()) 'rendered.yaml')

# Kustomize
kustomize build overlays/<env>

# Policy / security (if installed)
kubeconform -strict -summary <files>
kube-linter lint <files>
checkov -d .
```

## 7. Hand off

```
HELM/KUSTOMIZE IMPLEMENTATION COMPLETE
- Packaging: helm | kustomize | raw
- Files: <list>
- New/changed workloads: <list>
- Resource asks: <CPU/mem totals>
- Validation: ✅ all clean / ⚠️ warnings: <list>
- Open items for review: <if any>
```

## 8. What you do NOT do

- Don't `kubectl apply` to a real cluster — handoff to `azure-deploy` or the user.
- Don't provision the cluster itself — that's `bicep-implementation` / `terraform-azure-implementation` + `azure-kubernetes`.
- Don't commit.

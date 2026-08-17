# Task 10 — Migrate a Helm chart to a Kustomize overlay

## User story

As a platform engineer, I want to migrate our **`orders-api`** workload off Helm and onto
Kustomize, so the platform team has one templating tool to maintain instead of two.

## Context

- Existing Helm chart lives at `deploy/helm/orders-api/` with `Chart.yaml`, `values.yaml`,
  and templates for: `deployment.yaml`, `service.yaml`, `configmap.yaml`, `hpa.yaml`,
  `serviceaccount.yaml`, `networkpolicy.yaml`.
- Three environments today: `dev`, `staging`, `prod` — each has its own `values-<env>.yaml`
  overriding image tag, replica count, resource limits, ingress host, and the env-specific
  config-map values.
- The migration must produce **the same rendered manifests** (modulo whitespace / ordering)
  as `helm template` does today, so the diff at `kubectl apply` time is empty.

## Requested deliverable

1. New layout under `deploy/kustomize/orders-api/`:
   - `base/` — the six resources above as plain manifests, with sensible defaults.
   - `overlays/dev/`, `overlays/staging/`, `overlays/prod/` — each containing a
     `kustomization.yaml` plus patches for the values that differ per env.
2. A short `deploy/kustomize/orders-api/README.md` documenting the layout and the
   `kubectl kustomize` commands for each env.
3. The original `deploy/helm/orders-api/` is deleted in the same change.
4. A migration note in `docs/migrations/2026-helm-to-kustomize.md` calling out any
   intentional differences (e.g., dropped Helm hooks).

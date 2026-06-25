# Acceptance criteria — task-10

1. **Kustomize renders cleanly** — `kubectl kustomize deploy/kustomize/orders-api/overlays/dev`
   (and `staging`, `prod`) all exit 0 with no errors.
2. **Manifest equivalence** — the rendered output of each overlay is functionally equivalent
   to `helm template ./deploy/helm/orders-api -f values-<env>.yaml` (same Kinds, names,
   replica counts, image tags, resource limits, ingress hosts). Diff is whitespace/ordering
   only.
3. **Helm chart removed** — `deploy/helm/orders-api/` no longer exists in the working tree.
4. **README present** — `deploy/kustomize/orders-api/README.md` documents layout and gives
   the `kubectl kustomize` command per environment.
5. **Migration note present** — `docs/migrations/2026-helm-to-kustomize.md` exists and
   lists at least one intentional difference (or explicitly states "no intentional
   differences").

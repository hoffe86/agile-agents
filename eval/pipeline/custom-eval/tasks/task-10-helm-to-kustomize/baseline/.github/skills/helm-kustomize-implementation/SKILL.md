---
name: helm-kustomize-implementation
description: >-
  Task-local reference for migrating the supplied Orders Helm chart to Kustomize.
---

Compare rendered resources, not just source YAML. Keep shared base resources and
explicit environment patches; preserve names, labels and workload settings.
Use the supplied values and declared render commands. The baseline has no Ingress:
PUBLIC_BASE_URL is not proof of the literal ingress-host acceptance criterion.
Missing render tools leave equivalence unverified. Do not deploy.

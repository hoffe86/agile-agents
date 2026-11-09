---
name: cicd-pipeline-implementation
description: >-
  Task-local reference for the requested Web GitHub Actions OIDC workflow.
---

Keep test/build evidence before deployment and permissions at the smallest job
scope. Use federated identity, never a stored client secret. Inspect existing
project paths and declared commands; validate with actionlint when available.
Author only the requested workflow; do not run a deployment or publish changes.

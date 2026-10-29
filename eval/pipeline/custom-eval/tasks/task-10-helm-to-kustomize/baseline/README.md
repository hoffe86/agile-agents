# Task 10 fixture note

This is a synthetic chart containing exactly the six resources named in the task prompt.
There is no Kubernetes `Ingress` resource in that list or in these templates. Each
environment's `ingress.host` value is consumed only as `PUBLIC_BASE_URL` in the
application ConfigMap. It is not an ingress-controller hostname.

The prompt's manifest-equivalence acceptance criterion mentions comparing ingress hosts.
This fixture preserves the environment-specific host as chart configuration without
inventing a seventh resource; that acceptance phrase remains ambiguous for a chart with
no `Ingress` object and must not be silently treated as proof of Ingress equivalence.

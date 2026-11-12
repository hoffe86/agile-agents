---
name: bicep-implementation
description: >-
  Task-local Bicep storage-module guidance for modules/ and examples/.
---

Use typed parameters with descriptions and explicit validation. Keep required
storage security settings visible, and consume the module from the example.
Validate both files with the declared tooling; missing Azure/Bicep tools are
unverified, not successful validation. Do not deploy.

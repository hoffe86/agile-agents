---
name: csharp-implementation
description: >-
  Task-local Pricing typed-HTTP-client resilience implementation conventions.
---

Preserve typed-client registration and the existing public contract. Bound retry
and timeout behaviour; distinguish transient from permanent failures and honour
cancellation. Verify APIs against the project's package version, not memory.
Use declared build commands and do not call the real pricing service.

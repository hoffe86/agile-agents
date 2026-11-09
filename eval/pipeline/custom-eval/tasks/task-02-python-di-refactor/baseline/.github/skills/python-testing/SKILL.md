---
name: python-testing
description: >-
  Task-local pytest guidance for invoice summariser dependency-injection tests.
---

Inject small deterministic fakes; assert existing success and error behaviour
without monkeypatching globals. Keep tests independent of network and time.
Run the profile's pytest command and report its actual result.

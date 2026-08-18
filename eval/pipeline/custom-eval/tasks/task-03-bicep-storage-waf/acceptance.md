# Acceptance criteria — task-03

1. **Builds** — `bicep build modules/storage-account.bicep` and
   `bicep build examples/storage-account-consumer.bicep` exit 0 with no errors and
   no warnings.
2. **Hardening present** — the rendered ARM JSON contains all six required properties
   (`minimumTlsVersion`, `supportsHttpsTrafficOnly`, `allowBlobPublicAccess`,
   `allowSharedKeyAccess`, network-ACL `defaultAction`, system-assigned identity).
3. **Parameter validation** — `name` parameter has a `@minLength(3)` / `@maxLength(24)`
   decorator; `sku` has an `@allowed([...])` decorator with the three values listed.
4. **Outputs match spec** — module exposes `id`, `name`, and `principalId` outputs.
5. **Documentation present** — `modules/storage-account.md` has a parameters table, an
   outputs table, and at least one usage snippet.

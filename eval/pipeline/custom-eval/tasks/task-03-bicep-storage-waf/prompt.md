# Task 03 — Add a Bicep module for an Azure Storage Account with WAF baseline

## User story

As a platform engineer, I need a reusable Bicep module `modules/storage-account.bicep` that
provisions an Azure Storage Account meeting our **Well-Architected Framework security
baseline**, so application teams can consume it without re-implementing the same hardening
in every workload.

## Required hardening

The module must enforce:

- TLS 1.2 minimum (`minimumTlsVersion: 'TLS1_2'`)
- HTTPS-only traffic (`supportsHttpsTrafficOnly: true`)
- Public blob access disabled (`allowBlobPublicAccess: false`)
- Shared-key access disabled (`allowSharedKeyAccess: false`) — Entra-only
- Network ACL default action: `Deny`; allow only the VNet/subnets passed in via parameters
- Customer-managed-key support is **optional** but parameterisable
- System-assigned managed identity enabled

## Inputs (parameters)

- `name` (required, string, validated against the storage-account naming rules)
- `location` (required, string)
- `sku` (default `Standard_LRS`, allowed values: `Standard_LRS | Standard_ZRS | Standard_GRS`)
- `allowedSubnets` (array of subnet resource IDs, default `[]`)
- `tags` (object, default `{}`)

## Outputs

- `id` — the storage account resource ID
- `name` — the storage account name
- `principalId` — the system-assigned managed identity principal ID

## Deliverables

1. The Bicep module file at `modules/storage-account.bicep`.
2. A short `modules/storage-account.md` documenting parameters, outputs, and a usage example.
3. A consumer example in `examples/storage-account-consumer.bicep` that wires the module
   into an existing resource group with one allowed subnet.

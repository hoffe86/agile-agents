# Task 08 — Threat-model a new external API surface

## User story

As security lead, I need a STRIDE threat model for the new **public** REST API we are about
to expose at `https://api.contoso.com/v1/quotes`, so we can identify and mitigate risks
before go-live.

## Context

The new API surface:

- Endpoint: `POST /v1/quotes` — partner submits a quote request and receives a quote ID
- Endpoint: `GET  /v1/quotes/{id}` — partner polls for the quote result
- Authentication: OAuth 2.0 client-credentials (machine-to-machine) issued by Entra ID
- Authorisation: scope `quotes.write` for POST, `quotes.read` for GET
- Data: each quote contains pricing PII (customer email, vehicle VIN, requested coverage)
- Backend: ASP.NET minimal API behind Azure Front Door + WAF, calling an internal pricing engine
- Rate limit: 100 req/min per client, enforced at Front Door
- Hosted in Azure West Europe (single region for the MVP)

## Requested deliverable

A Markdown threat model at `docs/security/threat-model-quotes-api.md` that:

1. Includes a short data-flow description (text only, no diagram tooling required) and lists
   trust boundaries (internet ↔ Front Door, Front Door ↔ App, App ↔ pricing engine).
2. Walks through each STRIDE category (Spoofing, Tampering, Repudiation, Information
   Disclosure, Denial of Service, Elevation of Privilege) with **at least one identified
   threat per category**.
3. For each threat: assigns a severity (Low/Med/High), a likely-affected asset, and at least
   one concrete mitigation already in place or to be implemented.
4. Calls out **at least three "must fix before go-live"** items as a separate section at the
   top so they're not lost in the table.

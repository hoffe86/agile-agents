# Acceptance criteria — task-08

1. **File exists** at `docs/security/threat-model-quotes-api.md` and is non-empty Markdown.
2. **STRIDE complete** — exactly six STRIDE category subsections appear (S, T, R, I, D, E),
   each with at least one identified threat. No category left empty.
3. **Per-threat metadata** — each threat row/entry has severity (Low | Med | High), affected
   asset, and at least one mitigation. Missing fields fail this criterion.
4. **Go-live blockers section** — a clearly marked section near the top lists at least 3
   "must fix before go-live" items, each cross-referencing the relevant STRIDE entry.
5. **Authoritative grounding** — the document references at least one of: OWASP API Security
   Top 10, Microsoft SDL threat-modelling guidance, or NIST SP 800-204. Marketing-blog
   citations alone do not satisfy this criterion.

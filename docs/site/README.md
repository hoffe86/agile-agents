# Documentation site

This private npm package builds the static documentation site. It does not change
plugin installation requirements. Canonical Markdown stays in `docs/` and `eval/`;
do not edit `.generated/`, `.docusaurus/` or `build/`.

## Local commands

Use Node 24 (verified with 24.22.3) and npm 12 (verified with 12.2.1).
From the repository root:

```sh
npm ci --prefix docs/site --ignore-scripts --no-audit --no-fund
npm run install:browser --prefix docs/site
npm test --prefix docs/site
npm run build --prefix docs/site
npm run test:build --prefix docs/site
DOCS_SITE_BASE_URL=http://127.0.0.1:4173/agile-agents/ npm run test:browser --prefix docs/site
npm run serve --prefix docs/site -- --port 3000
```

Open `http://127.0.0.1:3000/agile-agents/`. For live editing, use
`npm start --prefix docs/site -- --port 3000`. Changes to canonical source files
require restarting the development server to regenerate the projection. Search
is generated from production HTML; verify it with `build` followed by `serve`,
not the development server.

The site uses Docusaurus classic's default components and a small original color
palette. There is no copied theme, animation framework, analytics, hosted search
or AI search. Local search downloads a static index and runs in the browser.
It is **not** a service worker, offline application, or promise that pages can be
opened without a network connection.

## Publication boundary

`publication.mjs` lists exact repository-relative Markdown paths and required
public assets. The config validates and regenerates an ignored disposable
`.generated/content/` tree before starting or building, preserving the `docs/`
and `eval/` prefixes. `npm run project --prefix docs/site` runs this step alone.
Adding a document or asset requires an explicit allowlist change; there is no
recursive repository copy. Fixtures, task inputs, run outputs, dependencies and
site internals are excluded even if accidentally listed.

Markdown links between published pages remain within the shared docs instance.
Other repository files/directories become GitHub `blob/main` / `tree/main` URLs
only after checking the original target exists. Markdown fragments are checked
even on unpublished files; non-Markdown file fragments must be valid GitHub line
references. Edit links return to the original repository file, never the staged
copy. Source branches for these links are defined in `publication.mjs`.

Links/images use Markdown syntax, including reference definitions. `.md` uses
CommonMark rather than MDX; JSX-like prose and CLI placeholders are literal text.
All raw HTML, including comment-prefixed nodes, is treated as literal text rather
than navigation or executable markup. Use Markdown headings/links/images instead.
Link validation is AST-based and ignores fenced code examples. Missing targets,
missing heading anchors, unallowlisted local images, symlinks and repository
escapes fail the build. Docusaurus also fails on unresolved generated
links/anchors.

The allowlist includes the four section entry and starter pages under
`docs/introduction/`, `docs/getting-started/` and `docs/flow/`, the existing docs
hub, ownership/mapping references, ADRs and selected evaluation guides.
`eval/baselines.md` is not published: its existing `./scoring-rubric.md` link is
unresolved. Links to it still open its validated canonical GitHub location.

Versions are exact and the lockfile is committed with the site package. The
projection uses the same unified/remark AST ecosystem shipped by Docusaurus;
tests use Node's built-in test runner, not a copied external test stack.
Search 0.52.3 supports Docusaurus 3 and React 19 without the later optional
AI-search peer.

## Dependency advisories

Docusaurus 3.10.2 (latest at adoption) pulls build-time transitives with
published advisories. Two exact `overrides` in `package.json` move them to fixed
releases, verified by the full build and both test suites:

| Package | Override | Advisory |
|---|---|---|
| `tinypool` | `2.2.0` | Critical prototype-pollution gadgets (GHSA-5gmw-xhrv-c9v3, GHSA-85c8-ppgw-ccpr) |
| `serialize-javascript` | `7.1.4` | Low; affected `<=7.1.2` (7.1.4 is patched) |

Remaining after overrides: `uuid <11.1.1` (moderate, reached only through the
local development server's `sockjs`, which does not use the affected v3/v5/v6
buffer path) and `deepmerge` (low, no fix published). Neither ships in the static
output. Do not use `npm audit fix --force`: it downgrades Docusaurus. Remove an
override once Docusaurus depends on a fixed release, and recheck the audit after
any dependency upgrade.

## Publishing to GitHub Pages

`.github/workflows/docs-site.yml` runs the projection tests, production build and
production output tests on pull requests and pushes that touch `docs/`, `eval/`,
`plugins/`, `.github/`, `README.md` or `AGENTS.md` — published pages link into
all of them, so moving a target must rerun the link check — plus a weekly
scheduled run that catches any remaining drift. The build job installs pinned
Playwright Chromium and runs production browser checks for keyboard navigation,
local search, cross-section links, mobile navigation, prefixed assets and visible
prose-link underlines. Failed browser runs retain traces and screenshots for
seven days. `testing.e2e` in `.github/solution-profile.yaml` records the browser,
base URL, headless setting, single-worker execution and zero-retry policy. Pull
requests and scheduled runs never deploy. A push to `main` (or
a manual run on `main`) uploads the build output of that same run as the Pages
artifact, and a separate job with only `pages: write` and
`id-token: write` deploys it. Actions are pinned by commit SHA.

The workflow being present does **not** mean the site is live. A maintainer must
enable it once: **Settings → Pages → Build and deployment → Source: GitHub
Actions**. Then create the `github-pages` environment yourself (Settings →
Environments), restrict its deployment branches to `main`, and configure at
least one required human reviewer **before** the first deploy. These are
required user-owned pre-deployment controls, not housekeeping: the
workflow's `main`-only guard can be edited on a branch by anyone with write
access, so only the environment policy actually prevents publishing from an
unreviewed branch. Neither Pages setup nor deployment occurred here; a
read-only live lookup confirmed that the `github-pages` environment is absent
(404), so its branch restriction and required-reviewer controls remain to be
configured. Until Pages is enabled, the deploy job on `main` fails at
`configure-pages`; the build and tests still gate every change. The intended
site URL is
`https://hoffe86.github.io/agile-agents/`. Keep its URL and branch coordinates
synchronized when the repository owner/name, Pages host or path, or source/deploy
branch changes:

- `docs/site/publication.mjs`: `repositoryUrl` drives canonical GitHub links, and
  `sourceBranch` drives edit links and published links to repository files.
- `docs/site/docusaurus.config.mjs`: `url` is the Pages origin and `baseUrl` is
  the site path prefix; together they produce the published site URL. Its GitHub
  navbar link uses `repositoryUrl` from `publication.mjs`.
- `.github/workflows/docs-site.yml`: deployment currently targets `main`. If the
  source/deploy branch changes, update its branch filters and deployment guards,
  plus the `github-pages` environment's allowed branches.

For an owner/repository move, update `publication.mjs`'s repository URL and the
Docusaurus Pages origin/path as applicable; for a Pages-host or path change,
update `url` and `baseUrl`. Recheck the rendered canonical links, edit links,
prefixed assets and Pages URL after changing these coordinates.

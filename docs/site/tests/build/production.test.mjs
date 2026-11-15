import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { load } from 'cheerio';
import { documents } from '../../publication.mjs';

const exec = promisify(execFile);
const site = fileURLToPath(new URL('../../', import.meta.url));
const output = path.join(site, 'build');

async function page(relative) {
  return load(await readFile(path.join(output, relative, 'index.html'), 'utf8'));
}

test('production landing exposes four primary sections under the Pages prefix', async () => {
  const $ = await page('');
  assert.equal($('link[rel="canonical"]').attr('href'), 'https://hoffe86.github.io/agile-agents/');
  assert.deepEqual($('.navbar__items:not(.navbar__items--right) > .navbar__link').map((_, a) => ({
    label: $(a).text(),
    href: $(a).attr('href'),
  })).get(), [
    { label: 'Introduction', href: '/agile-agents/' },
    { label: 'Getting started', href: '/agile-agents/docs/getting-started/' },
    { label: 'Flow', href: '/agile-agents/docs/flow/' },
    { label: 'Evaluation', href: '/agile-agents/eval/' },
  ]);
});

test('production docs to eval and eval to docs links retain the shared prefix', async () => {
  const docs = await page('docs');
  const evaluation = await page('eval');
  const adr = await page('docs/adr/deepeval-for-pipeline-evaluation');
  const evalLinks = docs('article a').toArray().map((link) => docs(link).attr('href'))
    .filter((href) => href.includes('/eval/'));
  const internal = evalLinks.filter((href) => !href.startsWith('https://github.com/'));
  assert.ok(internal.includes('/agile-agents/eval/'));
  assert.ok(internal.every((href) => href.startsWith('/agile-agents/eval/')), internal.join(', '));
  const markdownLinks = docs('article a').toArray().map((link) => docs(link).attr('href'))
    .filter((href) => !/^https?:/.test(href) && /\.md(#|\?|$)/.test(href));
  assert.deepEqual(markdownLinks, []);
  assert.equal(evaluation('article a[href="/agile-agents/docs/adr/deepeval-for-pipeline-evaluation/"]').length, 1);
  assert.match(adr('h1').text(), /ADR 0015/);
});

test('canonical anchors, GitHub fallbacks and edit links survive production rendering', async () => {
  const gettingStarted = await page('docs/getting-started');
  const docs = await page('docs');
  const evaluation = await page('eval');
  assert.equal(gettingStarted('article a[href="/agile-agents/docs/#solution-profile-canvas"]').length, 1);
  assert.equal(docs('#solution-profile-canvas').length, 1);
  assert.equal(docs('article a[href="https://github.com/hoffe86/agile-agents/blob/main/README.md"]').length, 1);
  assert.equal(docs('article a[href="https://github.com/hoffe86/agile-agents/tree/main/plugins/agile-agents-core/extensions/solution-profile"]').length, 1);
  assert.equal(docs('.theme-edit-this-page').attr('href'),
    'https://github.com/hoffe86/agile-agents/edit/main/docs/README.md');
  assert.equal(evaluation('.theme-edit-this-page').attr('href'),
    'https://github.com/hoffe86/agile-agents/edit/main/eval/README.md');
});

test('only needed public image is emitted and referenced at the Pages prefix', async () => {
  const $ = await page('docs/flow');
  const src = $('article img').attr('src');
  assert.match(src, /^\/agile-agents\/assets\/images\/rpi-pipeline-[a-f\d]+\.png$/);
  const built = await readFile(path.join(output, src.slice('/agile-agents/'.length)));
  const canonical = await readFile(path.join(site, '../assets/rpi-pipeline.png'));
  assert.deepEqual(built, canonical);
  assert.equal($('article img').attr('alt'), 'Research, Plan, Implement and Review pipeline');
});

test('canonical literal CLI placeholders render as text without JSX interpretation', async () => {
  const $ = await page('eval/pipeline/custom-eval');
  assert.match($('article').text(), /task-NN-<kebab-slug>/);
  assert.equal($('kebab-slug').length, 0);
});

test('static search includes published docs only and uses the Pages prefix', async () => {
  const files = await readdir(output);
  const indexes = files.filter((name) => /^search-index-[a-f\d]+\.json$/.test(name));
  assert.equal(indexes.length, 1);
  const index = JSON.parse(await readFile(path.join(output, indexes[0]), 'utf8'));
  const pages = index[0].documents;
  assert.equal(pages.length, documents.length);
  assert.equal(pages.some((doc) => doc.t === 'Evaluation' && doc.u === '/agile-agents/eval/'), true);
  assert.equal(pages.every((doc) => doc.u.startsWith('/agile-agents/')), true);
  assert.equal(pages.some((doc) => /\/(site|fixtures|runs|node_modules)\//.test(doc.u)), false);
  const $ = await page('');
  assert.equal($('input[aria-label="Search"]').length, 1);
});

async function buildFixture(t, markdown) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'docs-build-rejection-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const fixtureSite = path.join(root, 'docs/site');
  await mkdir(path.join(fixtureSite, 'scripts'), { recursive: true });
  await mkdir(path.join(fixtureSite, 'src/css'), { recursive: true });
  await mkdir(path.join(root, 'eval'));
  const config = await readFile(path.join(site, 'docusaurus.config.mjs'), 'utf8');
  await writeFile(path.join(fixtureSite, 'docusaurus.config.mjs'),
    config.replace("onBrokenLinks: 'throw'", "onBrokenLinks: 'ignore'"));
  await copyFile(path.join(site, 'scripts/project.mjs'), path.join(fixtureSite, 'scripts/project.mjs'));
  await writeFile(path.join(fixtureSite, 'sidebars.cjs'),
    "module.exports = { introduction: ['docs/a'], gettingStarted: ['docs/a'], flow: ['docs/a'], evaluation: ['eval/b'] };\n");
  await writeFile(path.join(fixtureSite, 'src/css/custom.css'), '');
  await writeFile(path.join(fixtureSite, 'publication.mjs'),
    `export { repositoryUrl, sourceBranch, editUrl } from ${JSON.stringify(new URL('../../publication.mjs', import.meta.url).href)};\n` +
    `export const documents = ['docs/a.md', 'eval/b.md'];\nexport const assets = [];\n`);
  await writeFile(path.join(root, 'docs/a.md'), markdown);
  await writeFile(path.join(root, 'eval/b.md'), '# Evaluation\n');
  await symlink(path.join(site, 'node_modules'), path.join(fixtureSite, 'node_modules'), 'dir');
  return {
    fixtureSite,
    build: () => exec(process.execPath, [
      path.join(site, 'node_modules/@docusaurus/core/bin/docusaurus.mjs'),
      'build', fixtureSite,
    ], {
      cwd: fixtureSite,
      timeout: 30000,
      maxBuffer: 1024 * 1024,
      env: { ...process.env, NO_COLOR: '1' },
    }),
  };
}

async function rejectedBuild(t, markdown) {
  const fixture = await buildFixture(t, markdown);
  return fixture.build();
}

test('production build command fails for invalid unpublished source targets, even with anchors', async (t) => {
  await assert.rejects(rejectedBuild(t, '[Missing](../missing.md#run)\n'),
    (error) => error.code === 1 && /ENOENT/.test(error.stderr));
});

test('production build command fails for unresolved internal anchors', async (t) => {
  await assert.rejects(rejectedBuild(t, '[Missing](../eval/b.md#absent)\n'),
    (error) => error.code === 1 && /Unresolved anchor: eval\/b.md#absent/.test(error.stderr));
});

test('production rendering escapes comment-prefixed HTML instead of executing it', async (t) => {
  const input = '<!-- benign --><script>globalThis.pwned = true</script>\n';
  const fixture = await buildFixture(t, input);
  await fixture.build();
  const html = await readFile(path.join(fixture.fixtureSite, 'build/docs/a/index.html'), 'utf8');
  const $ = load(html);
  assert.ok($('article').text().includes(input.trim()),
    'literal HTML-like input should remain visible in production output');
  assert.equal($('article script').length, 0);
});

test('site configuration keeps broken links and anchors fatal', async () => {
  const { default: createConfig } = await import('../../docusaurus.config.mjs');
  const config = await createConfig();
  assert.equal(config.onBrokenLinks, 'throw');
  assert.equal(config.onBrokenAnchors, 'throw');
  assert.equal(config.markdown.hooks.onBrokenMarkdownLinks, 'throw');
  assert.equal(config.markdown.hooks.onBrokenMarkdownImages, 'throw');
});

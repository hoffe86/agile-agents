import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { visit } from 'unist-util-visit';
import { createProjection, project, remarkRepositoryLinks } from '../scripts/project.mjs';
import { editUrl } from '../publication.mjs';

const manifest = { documents: ['docs/a.md', 'eval/b.md'], assets: ['docs/assets/pipeline.png'] };
const initialFiles = {
  'docs/a.md': '# A\n\n[Evaluation](../eval/b.md#shared)\n\n![Pipeline](assets/pipeline.png)\n',
  'eval/b.md': '# Evaluation\n\n## Shared\n\n[Docs](../docs/a.md#a)\n',
  'docs/assets/pipeline.png': 'test asset',
  'README.md': '# Repo\n\n## Install\n',
  'plugins/tool.md': '# Tool\n\n## Run\n',
  'docs/fixtures/private.md': '# Excluded\n',
  'eval/pipeline/runs/output.md': '# Excluded\n',
  'docs/site/internal.md': '# Excluded\n',
  'docs/site/node_modules/dependency.md': '# Excluded\n',
};

async function fixture(t, overrides = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'docs-projection-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const [relative, content] of Object.entries({ ...initialFiles, ...overrides })) {
    await mkdir(path.dirname(path.join(root, relative)), { recursive: true });
    await writeFile(path.join(root, relative), content);
  }
  return root;
}

async function transformed(root, content, source = 'docs/a.md', selection = manifest) {
  const projection = createProjection({ repoRoot: root, ...selection });
  return projection.transform(projection.parse(content), source);
}

function urls(tree) {
  const result = [];
  visit(tree, (node) => {
    if (node.url) result.push(node.url);
  });
  return result;
}

test('projects only exact allowlisted files, retains prefixes and canonical bytes', async (t) => {
  const root = await fixture(t);
  const output = await project(root, manifest);
  assert.deepEqual((await readdir(output)).sort(), ['docs', 'eval']);
  assert.deepEqual((await readdir(path.join(output, 'docs'))).sort(), ['a.md', 'assets']);
  assert.deepEqual((await readdir(path.join(output, 'eval'))).sort(), ['b.md']);
  assert.equal(await readFile(path.join(output, 'docs/a.md'), 'utf8'), initialFiles['docs/a.md']);
  assert.equal(await readFile(path.join(output, 'docs/assets/pipeline.png'), 'utf8'), 'test asset');
  assert.equal(await readFile(path.join(root, 'docs/a.md'), 'utf8'), initialFiles['docs/a.md']);
});

test('reprojection removes stale content instead of accidentally publishing it', async (t) => {
  const root = await fixture(t);
  const output = await project(root, manifest);
  await writeFile(path.join(output, 'stale.md'), '# Old');
  await project(root, manifest);
  assert.deepEqual((await readdir(output)).sort(), ['docs', 'eval']);
});

test('resolves docs to eval and eval to docs within the shared tree', async (t) => {
  const root = await fixture(t);
  assert.deepEqual(urls(await transformed(root, initialFiles['docs/a.md'])), [
    '../eval/b.md#shared', 'assets/pipeline.png',
  ]);
  assert.deepEqual(urls(await transformed(root, initialFiles['eval/b.md'], 'eval/b.md')), [
    '../docs/a.md#a',
  ]);
});

test('maps existing unpublished files and directories to canonical GitHub URLs', async (t) => {
  const root = await fixture(t);
  const tree = await transformed(root,
    '[Install](../README.md#install) [Tool](../plugins/tool.md#run) [Sources](../plugins/)');
  assert.deepEqual(urls(tree), [
    'https://github.com/hoffe86/agile-agents/blob/main/README.md#install',
    'https://github.com/hoffe86/agile-agents/blob/main/plugins/tool.md#run',
    'https://github.com/hoffe86/agile-agents/tree/main/plugins',
  ]);
});

test('canonical edit URLs retain docs and eval repository paths', () => {
  assert.equal(editUrl({ docPath: 'docs/README.md' }),
    'https://github.com/hoffe86/agile-agents/edit/main/docs/README.md');
  assert.equal(editUrl({ docPath: 'eval/pipeline/scoring-rubric.md' }),
    'https://github.com/hoffe86/agile-agents/edit/main/eval/pipeline/scoring-rubric.md');
});

test('rewrites reference definitions, including images, without touching code examples', async (t) => {
  const root = await fixture(t);
  const tree = await transformed(root,
    '[Repo][repo] ![Diagram][image]\n\n[repo]: ../README.md#install\n[image]: assets/pipeline.png\n\n' +
    '```md\n[Missing](missing.md)\n```\n');
  assert.deepEqual(urls(tree), [
    'https://github.com/hoffe86/agile-agents/blob/main/README.md#install',
    'assets/pipeline.png',
  ]);
});

test('preserves external links and normalizes repository-root paths', async (t) => {
  const root = await fixture(t);
  assert.deepEqual(urls(await transformed(root,
    '[Web](https://example.test/a#b) [Mail](mailto:docs@example.test) [Root](/eval/b.md#shared)')), [
    'https://example.test/a#b', 'mailto:docs@example.test', '../eval/b.md#shared',
  ]);
});

test('decodes and re-encodes spaces and Unicode in repository paths', async (t) => {
  const root = await fixture(t, { 'docs/über view.md': '# Über\n' });
  const tree = await transformed(root, '[Other](%C3%BCber%20view.md#über)');
  assert.deepEqual(urls(tree), [
    'https://github.com/hoffe86/agile-agents/blob/main/docs/%C3%BCber%20view.md#über',
  ]);
});

test('accepts duplicate-heading anchors and explicit heading IDs', async (t) => {
  const root = await fixture(t, { 'eval/b.md': '# Evaluation\n\n## Shared\n\n## Shared\n\n## Custom {#stable}\n' });
  assert.deepEqual(urls(await transformed(root,
    '[Duplicate](../eval/b.md#shared-1) [Custom](../eval/b.md#stable)')), [
    '../eval/b.md#shared-1', '../eval/b.md#stable',
  ]);
});

test('validates GitHub line anchors on unpublished non-Markdown files', async (t) => {
  const root = await fixture(t, { 'scripts/example.py': 'first\nsecond\n' });
  assert.deepEqual(urls(await transformed(root, '[Lines](../scripts/example.py#L1-L2)')), [
    'https://github.com/hoffe86/agile-agents/blob/main/scripts/example.py#L1-L2',
  ]);
  await assert.rejects(transformed(root, '[Bad](../scripts/example.py#L3)'), /Unresolved anchor/);
});

test('normal CLI placeholders and JSX-like prose remain non-executable literal text', async (t) => {
  const root = await fixture(t);
  const tree = await transformed(root, 'Use <kebab-slug> when a < b and {value} is present.\n');
  assert.equal(tree.children[0].children.map((node) => node.value).join(''),
    'Use <kebab-slug> when a < b and {value} is present.');
  assert.equal(tree.children[0].children.some((node) => node.type === 'html'), false);
});

test('comment-prefixed HTML is retained as text rather than executable markup', async (t) => {
  const root = await fixture(t);
  const content = '<!-- benign --><script>globalThis.pwned = true</script>';
  const tree = await transformed(root, content);
  const paragraph = tree.children[0];
  assert.equal(paragraph?.type, 'paragraph');
  assert.equal(paragraph?.children[0]?.type, 'text');
  assert.equal(paragraph?.children[0]?.value, content);
  assert.equal(tree.children.some((node) => node.type === 'html'), false);
});

test('Docusaurus remark integration derives the original source path from the projection', async (t) => {
  const root = await fixture(t);
  const contentRoot = path.join(root, 'docs/site/.generated/content');
  const projection = createProjection({ repoRoot: root, ...manifest });
  const tree = projection.parse('[Repo](../README.md#install)');
  await remarkRepositoryLinks({ repoRoot: root, contentRoot, ...manifest })(
    tree, { path: path.join(contentRoot, 'docs/a.md') },
  );
  assert.deepEqual(urls(tree), ['https://github.com/hoffe86/agile-agents/blob/main/README.md#install']);
});

for (const [name, content, expected] of [
  ['missing published target', '[Missing](../eval/missing.md#shared)', /ENOENT/],
  ['missing unpublished target with an anchor', '[Missing](../plugins/missing.md#run)', /ENOENT/],
  ['missing published anchor', '[Missing](../eval/b.md#missing)', /Unresolved anchor/],
  ['missing unpublished anchor', '[Missing](../README.md#missing)', /Unresolved anchor/],
  ['missing same-page anchor', '[Missing](#missing)', /Unresolved anchor/],
  ['unallowlisted image', '![Other](../README.md)', /Image is not allowlisted/],
  ['image reference bypass', '![Other][image]\n\n[image]: ../README.md\n', /Image is not allowlisted/],
  ['path traversal', '[Outside](../../outside.md)', /Not a repository-relative path/],
  ['encoded path traversal', '[Outside](%2e%2e/%2e%2e/outside.md)', /Not a repository-relative path/],
  ['Windows separator', '[Outside](..%5coutside.md)', /Invalid path/],
  ['malformed path encoding', '[Bad](bad%xx.md)', /URI malformed/],
  ['unsafe scheme', '[Bad](javascript:alert)', /Unsupported URL/],
]) {
  test(`fails closed on ${name}`, async (t) => {
    const root = await fixture(t);
    await assert.rejects(transformed(root, content), expected);
  });
}

for (const relative of [
  'docs/site/internal.md',
  'docs/site/node_modules/dependency.md',
  'docs/fixtures/private.md',
  'eval/pipeline/runs/output.md',
  'eval/pipeline/custom-eval/tasks/task-01/prompt.md',
  'eval/results/report.md',
  '../outside.md',
  '/absolute.md',
  'docs/../README.md',
]) {
  test(`publication boundary rejects ${relative}`, async (t) => {
    const root = await fixture(t);
    await assert.rejects(project(root, { documents: [relative], assets: [] }),
      /publication boundary|repository-relative path/);
  });
}

for (const relative of ['docs/a.txt', 'docs/.private/x.md', 'eval/b.MD']) {
  test(`publication boundary rejects document ${relative}`, async (t) => {
    const root = await fixture(t);
    await assert.rejects(project(root, { documents: [relative], assets: [] }), /publication boundary/);
  });
}

for (const relative of ['eval/x.png', 'docs/x.png', 'docs/assets/x.html', 'docs/assets/x.md',
  'docs/assets/.hidden/x.png']) {
  test(`publication boundary rejects asset ${relative}`, async (t) => {
    const root = await fixture(t);
    await assert.rejects(project(root, { documents: ['docs/a.md'], assets: [relative] }),
      /publication boundary/);
  });
}

test('publication boundary accepts allowlisted image formats', async (t) => {
  const assets = ['docs/assets/pipeline.png', 'docs/assets/d.svg', 'docs/assets/p.jpeg',
    'docs/assets/p.jpg', 'docs/assets/a.gif', 'docs/assets/w.webp'];
  const root = await fixture(t, Object.fromEntries(assets.map((asset) => [asset, 'image'])));
  const output = await project(root, { documents: ['docs/a.md', 'eval/b.md'], assets });
  assert.deepEqual((await readdir(path.join(output, 'docs/assets'))).sort(),
    assets.map((asset) => path.basename(asset)).sort());
});

test('rejects duplicate or empty manifests', async (t) => {
  const root = await fixture(t);
  await assert.rejects(project(root, { documents: [], assets: [] }), /nonempty/);
  await assert.rejects(project(root, { documents: ['docs/a.md', 'docs/a.md'], assets: [] }), /unique/);
});

test('rejects missing and directory publication sources', async (t) => {
  const root = await fixture(t);
  await assert.rejects(project(root, { documents: ['docs/missing.md'], assets: [] }), /ENOENT/);
  await mkdir(path.join(root, 'docs/directory.md'));
  await assert.rejects(project(root, { documents: ['docs/directory.md'], assets: [] }), /not a file/);
});

test('rejects symlinked publication sources even when the target is inside the repo', async (t) => {
  const root = await fixture(t);
  await symlink(path.join(root, 'docs/a.md'), path.join(root, 'docs/linked.md'));
  await assert.rejects(project(root, { documents: ['docs/linked.md'], assets: [] }), /Symlink boundary/);
});

test('rejects symlinked intermediate directories when resolving GitHub fallbacks', async (t) => {
  const root = await fixture(t);
  await symlink(path.join(root, 'plugins'), path.join(root, 'linked'));
  await assert.rejects(transformed(root, '[Tool](../linked/tool.md#run)'), /Symlink boundary/);
});

test('rejects symlinked assets instead of copying their targets', async (t) => {
  const root = await fixture(t);
  await symlink(path.join(root, 'README.md'), path.join(root, 'docs/assets/linked.png'));
  await assert.rejects(project(root, {
    documents: manifest.documents, assets: ['docs/assets/linked.png'],
  }), /Symlink boundary/);
});

test('rejects symlinked generated roots without touching their targets', async (t) => {
  const root = await fixture(t);
  await symlink(path.join(root, 'plugins'), path.join(root, 'docs/site/.generated'));
  await assert.rejects(project(root, manifest), /Symlink boundary/);
  assert.equal(await readFile(path.join(root, 'plugins/tool.md'), 'utf8'), initialFiles['plugins/tool.md']);
});

test('rejects symlinked content roots without touching their targets', async (t) => {
  const root = await fixture(t);
  await mkdir(path.join(root, 'docs/site/.generated'));
  await symlink(path.join(root, 'plugins'), path.join(root, 'docs/site/.generated/content'));
  await assert.rejects(project(root, manifest), /Symlink boundary/);
  assert.equal(await readFile(path.join(root, 'plugins/tool.md'), 'utf8'), initialFiles['plugins/tool.md']);
});

test('invalid inputs fail validation before replacing the previous projection', async (t) => {
  const root = await fixture(t);
  const output = await project(root, manifest);
  await writeFile(path.join(root, 'docs/a.md'), '[Broken](missing.md)');
  await assert.rejects(project(root, manifest), /ENOENT/);
  assert.equal(await readFile(path.join(output, 'docs/a.md'), 'utf8'), initialFiles['docs/a.md']);
});

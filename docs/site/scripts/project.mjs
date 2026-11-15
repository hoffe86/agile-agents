import { copyFile, lstat, mkdir, readFile, realpath, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import GithubSlugger from 'github-slugger';
import { toString } from 'mdast-util-to-string';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkFrontmatter from 'remark-frontmatter';
import { visit } from 'unist-util-visit';
import { repositoryUrl, sourceBranch } from '../publication.mjs';

const parser = unified().use(remarkParse).use(remarkGfm).use(remarkFrontmatter);
const excluded = new Set([
  'site', 'node_modules', 'fixtures', 'tasks', 'runs', 'results', '.runs',
  'bin', 'obj', '__pycache__', '.venv', '.git',
]);

function assertRelative(relative) {
  if (!relative || path.posix.isAbsolute(relative) || relative.includes('\\') ||
      relative.split('/').some((part) => !part || part === '.' || part === '..')) {
    throw new Error(`Not a repository-relative path: ${relative}`);
  }
}

// Reject every symlink component, including links that point back into the repo.
// Existence checks happen before rewriting links to GitHub, never afterwards.
async function sourceTarget(repoRoot, relative) {
  assertRelative(relative);
  let target = repoRoot;
  for (const component of relative.split('/')) {
    target = path.join(target, component);
    const stat = await lstat(target);
    if (stat.isSymbolicLink()) throw new Error(`Symlink boundary: ${relative}`);
  }
  return { absolute: target, stat: await lstat(target) };
}

function assertPublishable(relative, asset) {
  assertRelative(relative);
  const parts = relative.split('/');
  if (!['docs', 'eval'].includes(parts[0]) ||
      parts.some((part) => part.startsWith('.') || excluded.has(part)) ||
      (asset
        ? !/^docs\/assets\/.+\.(png|jpe?g|gif|webp|svg)$/.test(relative)
        : !relative.endsWith('.md'))) {
    throw new Error(`Outside publication boundary: ${relative}`);
  }
}

function parse(source) {
  return parser.parse(source);
}

function anchors(tree) {
  const slugger = new GithubSlugger();
  const result = new Set();
  visit(tree, 'heading', (node) => {
    const heading = toString(node);
    const explicit = heading.match(/\s+\{#([^}]+)\}\s*$/);
    result.add(explicit ? explicit[1] : slugger.slug(heading));
  });
  return result;
}

export function createProjection({ repoRoot, documents, assets }) {
  const publishedDocs = new Set(documents);
  const publishedAssets = new Set(assets);
  const trees = new Map();

  async function treeFor(relative) {
    if (!trees.has(relative)) {
      const { absolute } = await sourceTarget(repoRoot, relative);
      trees.set(relative, parse(await readFile(absolute, 'utf8')));
    }
    return trees.get(relative);
  }

  async function validateAnchor(target, fragment, stat) {
    if (!fragment) return;
    const anchor = decodeURIComponent(fragment.slice(1));
    if (stat.isFile() && target.endsWith('.md')) {
      if (anchors(await treeFor(target)).has(anchor)) return;
    } else if (stat.isFile() && /^L\d+(-L\d+)?$/.test(anchor)) {
      const { absolute } = await sourceTarget(repoRoot, target);
      const lines = (await readFile(absolute, 'utf8')).trimEnd().split('\n').length;
      const [start, end = start] = anchor.slice(1).split('-L').map(Number);
      if (start >= 1 && end >= start && end <= lines) return;
    }
    throw new Error(`Unresolved anchor: ${target}${fragment}`);
  }

  async function resolveLink(source, url, image) {
    if (/^(https?:|mailto:|tel:)/i.test(url) || url.startsWith('//')) return url;
    if (/^[a-z][a-z\d+.-]*:/i.test(url)) throw new Error(`Unsupported URL: ${url}`);
    const match = url.match(/^([^?#]*)(\?[^#]*)?(#.*)?$/);
    if (!match) throw new Error(`Invalid link in ${source}: ${url}`);
    const [, encodedPath, query = '', fragment = ''] = match;
    const decoded = decodeURIComponent(encodedPath);
    if (decoded.includes('\\') || decoded.includes('\0')) {
      throw new Error(`Invalid path in ${source}: ${url}`);
    }
    // Leading slash means repository root, not an unchecked site route.
    const target = decoded
      ? path.posix.normalize(decoded.startsWith('/')
        ? decoded.slice(1)
        : path.posix.join(path.posix.dirname(source), decoded))
      : source;
    const { stat } = await sourceTarget(repoRoot, target.replace(/\/$/, ''));
    const normalized = target.replace(/\/$/, '');
    await validateAnchor(normalized, fragment, stat);

    if (image && !publishedAssets.has(normalized)) {
      throw new Error(`Image is not allowlisted: ${source} -> ${url}`);
    }
    if (publishedDocs.has(normalized) || publishedAssets.has(normalized)) {
      const relative = path.posix.relative(path.posix.dirname(source), normalized);
      return `${relative.split('/').map(encodeURIComponent).join('/')}${query}${fragment}`;
    }
    const kind = stat.isDirectory() ? 'tree' : 'blob';
    const encoded = normalized.split('/').map(encodeURIComponent).join('/');
    return `${repositoryUrl}/${kind}/${sourceBranch}/${encoded}${query}${fragment}`;
  }

  async function transform(tree, source) {
    if (!publishedDocs.has(source)) throw new Error(`Document is not allowlisted: ${source}`);
    const links = [];
    const definitions = new Map();
    visit(tree, (node) => {
      if (node.type === 'definition') definitions.set(node.identifier, node);
    });
    visit(tree, (node, index, parent) => {
      if (node.type === 'link' || node.type === 'image' || node.type === 'definition') {
        links.push({ node, image: node.type === 'image' });
      }
      if (node.type === 'linkReference' || node.type === 'imageReference') {
        const definition = definitions.get(node.identifier);
        if (!definition) throw new Error(`Unresolved reference: ${source}: ${node.identifier}`);
        if (node.type === 'imageReference') links.push({ node: definition, image: true });
      }
      // Canonical .md is prose, not executable JSX/HTML. Preserve literal CLI
      // placeholders and comparisons instead of interpreting them as elements.
      if (node.type === 'html') {
        node.type = 'text';
        // A root-level HTML block converted directly to text is dropped by the
        // Markdown renderer; put it in a paragraph so the literal remains visible.
        if (parent?.type === 'root') {
          parent.children[index] = {
            type: 'paragraph',
            children: [node],
            position: node.position,
          };
        }
      }
    });
    // Resolve before assigning: an image definition may also be used as a link.
    const resolved = await Promise.all(links.map(async ({ node, image }) => ({
      node, url: await resolveLink(source, node.url, image),
    })));
    for (const { node, url } of resolved) node.url = url;
    return tree;
  }

  return {
    async validate() {
      if (!documents.length || new Set([...documents, ...assets]).size !== documents.length + assets.length) {
        throw new Error('Publication manifest must be nonempty and contain unique paths');
      }
      for (const relative of [...documents, ...assets]) {
        assertPublishable(relative, assets.includes(relative));
        const { stat } = await sourceTarget(repoRoot, relative);
        if (!stat.isFile()) throw new Error(`Publication source is not a file: ${relative}`);
      }
      for (const source of documents) {
        // Keep the cached canonical AST unchanged for later anchor lookups.
        await transform(structuredClone(await treeFor(source)), source);
      }
    },
    transform,
    parse,
  };
}

export async function project(repoRoot, manifest) {
  repoRoot = await realpath(repoRoot);
  const projection = createProjection({ repoRoot, ...manifest });
  await projection.validate();
  const generated = 'docs/site/.generated';
  await sourceTarget(repoRoot, 'docs/site');
  // mkdir's nonrecursive mode will not follow a pre-existing generated symlink.
  try {
    await mkdir(path.join(repoRoot, generated));
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }
  await sourceTarget(repoRoot, generated);
  const contentRoot = path.join(repoRoot, generated, 'content');
  try {
    const stat = await lstat(contentRoot);
    if (stat.isSymbolicLink()) throw new Error('Symlink boundary: generated content');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  await rm(contentRoot, { recursive: true, force: true });
  for (const relative of [...manifest.documents, ...manifest.assets]) {
    const { absolute } = await sourceTarget(repoRoot, relative);
    const destination = path.join(contentRoot, relative);
    await mkdir(path.dirname(destination), { recursive: true });
    await copyFile(absolute, destination);
  }
  return contentRoot;
}

// Runs before Docusaurus's own link/image handling on the shared content tree.
export function remarkRepositoryLinks(options) {
  const projection = createProjection(options);
  return async (tree, file) => {
    const source = path.relative(options.contentRoot, file.path).split(path.sep).join('/');
    const parsed = file.value === undefined ? tree : projection.parse(file.value);
    const projected = await projection.transform(parsed, source);
    tree.children = projected.children;
    tree.position = projected.position;
  };
}

async function main() {
  const { documents, assets } = await import('../publication.mjs');
  const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));
  const contentRoot = await project(repoRoot, { documents, assets });
  console.log(`Projected ${documents.length} documents and ${assets.length} assets to ${contentRoot}`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();

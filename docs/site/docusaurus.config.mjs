import { fileURLToPath } from 'node:url';
import { documents, assets, editUrl, repositoryUrl } from './publication.mjs';

export default async function createConfig() {
  const { project, remarkRepositoryLinks } = await import('./scripts/project.mjs');
  const repoRoot = fileURLToPath(new URL('../../', import.meta.url));
  const contentRoot = await project(repoRoot, { documents, assets });

  return {
    title: 'Agile Agents',
    tagline: 'An agentic agile harness',
    url: 'https://hoffe86.github.io',
    baseUrl: '/agile-agents/',
    trailingSlash: true,
    onBrokenLinks: 'throw',
    onBrokenAnchors: 'throw',
    markdown: {
      format: 'detect',
      hooks: { onBrokenMarkdownLinks: 'throw', onBrokenMarkdownImages: 'throw' },
      anchors: { maintainCase: false },
    },
    presets: [
      ['classic', {
        docs: {
          path: contentRoot,
          routeBasePath: '/',
          sidebarPath: './sidebars.cjs',
          editUrl,
          beforeDefaultRemarkPlugins: [
            [remarkRepositoryLinks, { repoRoot, contentRoot, documents, assets }],
          ],
        },
        blog: false,
        pages: false,
        theme: { customCss: './src/css/custom.css' },
      }],
    ],
    themes: [
      ['@easyops-cn/docusaurus-search-local', {
        hashed: 'filename',
        language: 'en',
        indexBlog: false,
        indexPages: false,
        docsRouteBasePath: '/',
        docsDir: '.generated/content',
      }],
    ],
    themeConfig: {
      navbar: {
        title: 'Agile Agents',
        items: [
          { type: 'docSidebar', sidebarId: 'introduction', label: 'Introduction', position: 'left' },
          { type: 'docSidebar', sidebarId: 'gettingStarted', label: 'Getting started', position: 'left' },
          { type: 'docSidebar', sidebarId: 'flow', label: 'Flow', position: 'left' },
          { type: 'docSidebar', sidebarId: 'evaluation', label: 'Evaluation', position: 'left' },
          { href: repositoryUrl, label: 'GitHub', position: 'right' },
        ],
      },
      footer: {
        style: 'dark',
        copyright: 'Agile Agents · MIT licensed',
      },
    },
  };
}

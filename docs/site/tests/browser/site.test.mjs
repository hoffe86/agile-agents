import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import path from 'node:path';
import { test } from 'node:test';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const site = fileURLToPath(new URL('../../', import.meta.url));
const output = path.join(site, 'build');
const diagnostics = path.join(site, 'test-results');
const configuredBaseURL = process.env.DOCS_SITE_BASE_URL;
if (!configuredBaseURL) {
  throw new Error('DOCS_SITE_BASE_URL is required');
}
const target = new URL(configuredBaseURL);
if (!['127.0.0.1', 'localhost'].includes(target.hostname) || !target.port ||
    !target.pathname.endsWith('/')) {
  throw new Error('DOCS_SITE_BASE_URL must be a local base URL with a port and trailing slash');
}
const basePath = target.pathname;
const route = (path = '') => `${basePath}${path}`;
const contentTypes = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.ico', 'image/x-icon'],
  ['.jpeg', 'image/jpeg'],
  ['.jpg', 'image/jpeg'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
]);
const serverErrors = [];
const missingFiles = [];

async function serveBuild(request, response) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    response.writeHead(405, { Allow: 'GET, HEAD' }).end();
    return;
  }

  let pathname;
  try {
    pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
  } catch {
    response.writeHead(400).end('Invalid URL');
    return;
  }

  if (!pathname.startsWith(basePath)) {
    response.writeHead(404).end('Not found');
    return;
  }

  let relativePath = pathname.slice(basePath.length);
  if (!relativePath || relativePath.endsWith('/')) relativePath += 'index.html';
  const file = path.resolve(output, relativePath);
  if (!file.startsWith(`${output}${path.sep}`)) {
    response.writeHead(404).end('Not found');
    return;
  }

  try {
    const body = await readFile(file);
    response.writeHead(200, {
      'Cache-Control': 'no-store',
      'Content-Length': body.length,
      'Content-Type': contentTypes.get(path.extname(file)) ?? 'application/octet-stream',
    });
    response.end(request.method === 'HEAD' ? undefined : body);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    missingFiles.push(relativePath);
    response.writeHead(404).end('Not found');
  }
}

async function tabTo(page, selector) {
  for (let count = 0; count < 60; count++) {
    await page.keyboard.press('Tab');
    if (await page.evaluate((href) =>
      document.activeElement?.getAttribute('href') === href, selector)) return;
  }
  assert.fail(`Keyboard focus did not reach ${selector}`);
}

async function assertProseLinksAreDistinct(page, route) {
  await page.goto(`${baseURL}${route}`);
  const links = page.locator('.theme-doc-markdown p a');
  const count = await links.count();
  assert.ok(count > 0, `Expected prose links on ${route}`);
  for (let index = 0; index < count; index++) {
    const decoration = await links.nth(index).evaluate((link) =>
      getComputedStyle(link).textDecorationLine);
    assert.ok(decoration.includes('underline'), `Link is not underlined on ${route}`);
  }
}

async function assertPublishedProseLinksAreDistinct(page) {
  for (const pageRoute of [route(), route('eval/'), route('docs/flow/')]) {
    await assertProseLinksAreDistinct(page, pageRoute);
  }
}

let server;
let browser;
let baseURL;

test('built documentation works in a browser', async (t) => {
  server = createServer((request, response) => {
    void serveBuild(request, response).catch((error) => {
      response.writeHead(500).end('Failed to serve the production build');
      serverErrors.push(error);
    });
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(Number(target.port), target.hostname, resolve);
  });
  baseURL = target.origin;
  t.after(async () => {
    if (browser) await browser.close();
    if (server.listening) {
      await new Promise((resolve, reject) => server.close((error) =>
        error ? reject(error) : resolve()));
    }
  });
  browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {}),
  });
  await t.test('keyboard navigation reaches evaluation', async (t) => {
    await exercise(t, 'keyboard-navigation', async (page) => {
      await page.goto(`${baseURL}${route()}`);
      const evaluation = route('eval/');
      await tabTo(page, evaluation);
      await page.keyboard.press('Enter');
      await page.waitForURL(`**${evaluation}`);
      const heading = page.locator('article h1').filter({ hasText: /Evaluation/ });
      await heading.waitFor();
      assert.match(await heading.textContent(), /Evaluation/);
    });
  });

  await t.test('local search finds and opens bootstrap guidance', async (t) => {
    await exercise(t, 'local-search', async (page) => {
      const requests = [];
      page.on('request', (request) => requests.push(request.url()));
      await page.goto(`${baseURL}${route()}`);
      const search = page.getByLabel('Search', { exact: true });
      await search.focus();
      const searchRequestsStart = requests.length;
      await page.keyboard.type('bootstrap');
      const options = page.getByRole('option');
      await options.first().waitFor({ state: 'visible' });
      assert.ok(await options.count() > 0);
      await page.keyboard.press('Enter');
      await page.waitForURL(`**${route('docs/getting-started/bootstrap/**')}`);
      const heading = page.locator('article h1').filter({ hasText: /Bootstrap/ });
      await heading.waitFor();
      assert.match(await heading.textContent(), /Bootstrap/);
      assert.ok(requests.slice(searchRequestsStart)
        .every((url) => url.startsWith(baseURL)), 'Search made an external request');
    });
  });

  await t.test('local search shows an empty state without navigating', async (t) => {
    await exercise(t, 'local-search-empty', async (page) => {
      await page.goto(`${baseURL}${route()}`);
      const search = page.getByLabel('Search', { exact: true });
      await search.focus();
      await page.keyboard.type('no-matching-docs-query-93f84');
      await page.getByText('No results', { exact: true }).waitFor({ state: 'visible' });
      assert.equal(page.url(), `${baseURL}${route()}`);
    });
  });

  await t.test('evaluation links open canonical documentation under the prefix', async (t) => {
    await exercise(t, 'cross-section-link', async (page) => {
      await page.goto(`${baseURL}${route('eval/')}`);
      await page.getByRole('link', { name: 'ADR 0015', exact: true }).click();
      await page.waitForURL(`**${route('docs/adr/deepeval-for-pipeline-evaluation/**')}`);
      const heading = page.locator('article h1').filter({ hasText: /ADR 0015/ });
      await heading.waitFor();
      assert.match(await heading.textContent(), /ADR 0015/);
    });
  });

  await t.test('Reference exposes canonical ADRs in a nested subsection', async (t) => {
    await exercise(t, 'adr-reference-subsection', async (page) => {
      await page.goto(`${baseURL}${route()}`);
      const sidebar = page.locator('.theme-doc-sidebar-menu');
      await sidebar.getByRole('button', { name: 'Reference', exact: true }).click();
      await sidebar.getByRole('button', { name: 'ADRs', exact: true }).click();
      const adr = sidebar.locator(
        `a[href="${route('docs/adr/deepeval-for-pipeline-evaluation/')}"]`);
      await adr.waitFor({ state: 'visible' });
      await adr.click();
      await page.waitForURL(`**${route('docs/adr/deepeval-for-pipeline-evaluation/**')}`);
      const heading = page.locator('article h1').filter({ hasText: /ADR 0015/ });
      await heading.waitFor();
      assert.match(await heading.textContent(), /ADR 0015/);
    });
  });

  await t.test('mobile navigation opens and follows a section link', async (t) => {
    await exercise(t, 'mobile-navigation', async (page) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`${baseURL}${route()}`);
      const toggle = page.locator('.navbar .navbar__toggle');
      await toggle.focus();
      await page.keyboard.press('Enter');
      assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
      const sidebar = page.locator('.navbar-sidebar');
      await sidebar.waitFor({ state: 'visible' });
      await sidebar.evaluate((element) =>
        Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
      await page.getByRole('button', { name: 'Back to main menu' }).click();
      const evaluation = page.locator(`.navbar-sidebar a[href="${route('eval/')}"]`);
      await evaluation.waitFor({ state: 'visible' });
      await page.waitForFunction((href) => {
        const link = document.querySelector(`.navbar-sidebar a[href="${href}"]`);
        return link && !link.closest('[inert]');
      }, route('eval/'));
      await evaluation.click();
      await page.waitForURL(`**${route('eval/')}`);
      const heading = page.locator('article h1').filter({ hasText: /Evaluation/ });
      await heading.waitFor();
      assert.match(await heading.textContent(), /Evaluation/);
    });
  });

  await t.test('assets use the Pages prefix and prose links remain distinguishable', async (t) => {
    await exercise(t, 'assets-and-accessibility', async (page) => {
      await page.goto(`${baseURL}${route('docs/flow/')}`);
      const image = page.locator('article img').first();
      assert.ok((await image.getAttribute('src')).startsWith(route('assets/')));
      assert.ok(await image.evaluate((element) => element.complete && element.naturalWidth > 0));
      await assertPublishedProseLinksAreDistinct(page);
    });
  });
  assert.deepEqual(serverErrors, []);
  assert.deepEqual(missingFiles, []);
});

async function exercise(t, name, action) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });
  page.on('requestfailed', (request) => errors.push(`${request.url()} ${request.failure()?.errorText}`));
  let tracing = false;
  try {
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    tracing = true;
    await action(page);
    assert.deepEqual(errors, [], 'Browser emitted page or console errors');
    await context.tracing.stop();
    tracing = false;
  } catch (error) {
    t.diagnostic(`Browser console, page and network errors: ${JSON.stringify(errors)}`);
    t.diagnostic(`Missing files: ${JSON.stringify(missingFiles)}`);
    await mkdir(diagnostics, { recursive: true });
    try {
      await page.screenshot({ path: path.join(diagnostics, `${name}.png`), fullPage: true });
    } catch (screenshotError) {
      t.diagnostic(`Failed to capture browser screenshot: ${screenshotError.message}`);
    }
    if (tracing) {
      await context.tracing.stop({ path: path.join(diagnostics, `${name}.zip`) });
      tracing = false;
    }
    throw error;
  } finally {
    if (tracing) await context.tracing.stop();
    await context.close();
  }
}

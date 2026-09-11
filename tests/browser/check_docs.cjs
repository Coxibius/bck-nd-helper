/* Optional release check: node tests/browser/check_docs.cjs /path/to/docs/index.html /path/to/screenshots
 * Requires Playwright in the development environment, never in the Python wheel.
 * BCK_ND_BROWSER_CHANNEL can select an installed browser, e.g. msedge.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const examples = {
  infra: 'graph LR\n  API[Browser API] --> DB[(Database)]',
  seq: 'sequenceDiagram\n  participant Browser\n  participant API\n  Browser->>API: Request\n  API-->>Browser: Response',
  uml: 'classDiagram\n  class User {\n    +int id\n  }\n  class Admin {\n    +manage()\n  }\n  User <|-- Admin',
  er: 'erDiagram\n  USER ||--o{ ORDER : places\n  USER {\n    int id PK\n  }\n  ORDER {\n    int id PK\n  }',
};

async function checkPage(browser, url, origin, screenshotDir) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    offline: url.startsWith('file:'),
  });
  const externalRequests = [];
  const pageErrors = [];
  context.on('request', request => {
    if (/^https?:/.test(request.url()) && !request.url().startsWith(origin + '/')) {
      externalRequests.push(request.url());
    }
  });
  await context.route('**/*', route => {
    const address = route.request().url();
    return !/^https?:/.test(address) || address.startsWith(origin + '/')
      ? route.continue() : route.abort();
  });
  // Storage restrictions must not prevent the initial rendering or the buttons.
  await context.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage unavailable'); } });
    Object.defineProperty(navigator, 'clipboard', {
      value: { async writeText(value) { window.__docsCopied = value; } },
    });
  });
  const page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    await page.goto(url, { waitUntil: 'load' });
    try {
      await page.waitForFunction(() =>
        ['infra', 'seq', 'uml', 'er'].every(id =>
          document.querySelector('#' + id + '-view .diagram-status')?.dataset.state === 'ready'),
        null, { timeout: 60000 });
    } catch (error) {
      console.error('Initial rendering failed:', await page.evaluate(() =>
        ['infra', 'seq', 'uml', 'er'].map(id => ({ id,
          state: document.querySelector('#' + id + '-view .diagram-status')?.dataset.state,
          sourceChars: document.getElementById(id + '-source')?.value.length }))), pageErrors);
      throw error;
    }
    await context.setOffline(true);
    const fitWidth = await page.locator('#uml-view svg').evaluate(svg => svg.getBoundingClientRect().width);
    await page.getByRole('button', { name: 'uml diagram: actual', exact: true }).click();
    const actualWidth = await page.locator('#uml-view svg').evaluate(svg => svg.getBoundingClientRect().width);
    assert(actualWidth + 1 >= fitWidth, '100% must not shrink a fit-to-view diagram');
    await page.getByRole('button', { name: 'uml diagram: fit', exact: true }).click();
    if (screenshotDir && url.startsWith('file:')) {
      await fs.mkdir(screenshotDir, { recursive: true });
      await page.locator('#uml').screenshot({ path: path.join(screenshotDir, 'initial-uml-offline.png') });
    }

    const receipts = {};
    for (const [id, source] of Object.entries(examples)) {
      await page.locator('#' + id + '-source').fill(source);
      await page.waitForFunction(({ id, source }) => {
        const view = document.getElementById(id + '-view');
        return document.getElementById(id + '-source').value === source
          && view.querySelector('.diagram-status').dataset.state === 'ready'
          && view.querySelector('svg')?.textContent.includes(
            id === 'infra' ? 'Browser API' : id === 'seq' ? 'Response' : id === 'uml' ? 'Admin' : 'ORDER');
      }, { id, source });
      receipts[id] = await page.locator('#' + id + '-view svg').evaluate(svg => ({
        groups: svg.querySelectorAll('g').length,
        edges: svg.querySelectorAll('path, line, polyline').length,
        width: svg.viewBox.baseVal.width,
        height: svg.viewBox.baseVal.height,
        renderer: svg.dataset.renderer,
      }));
      assert(receipts[id].groups > 0 && receipts[id].edges > 0, `${id}: real diagram geometry missing`);
      assert(receipts[id].width > 0 && receipts[id].height > 0, `${id}: empty diagram bounds`);
      assert.equal(receipts[id].renderer, 'mermaid');
    }

    await page.locator('#copy-btn-uml').click();
    await page.waitForFunction(source => window.__docsCopied === source, examples.uml);
    await page.locator('#copy-ai-context-btn').click();
    await page.waitForFunction(() => window.__docsCopied === document.getElementById('ai-context-content').value);

    const previousDiagram = await page.locator('#uml-view .diagram-canvas').innerHTML();
    await page.locator('#uml-source').fill('classDiagram\n  class { deliberately invalid');
    await page.locator('#uml-view .diagram-status[data-state="error"]').waitFor();
    assert.equal(await page.locator('#uml-view .diagram-canvas').innerHTML(), previousDiagram);
    assert.match(await page.locator('#uml-view .diagram-status').innerText(), /last valid diagram/);
    await page.locator('#uml-source').fill(examples.uml);
    await page.waitForFunction(() => document.querySelector('#uml-view .diagram-status').dataset.state === 'ready');

    const previousThemeDiagram = await page.locator('#uml-view svg').getAttribute('id');
    await page.locator('#theme-toggle').click();
    await page.waitForFunction(previous =>
      document.querySelector('#uml-view .diagram-status').dataset.state === 'ready'
      && document.querySelector('#uml-view svg').id !== previous, previousThemeDiagram);

    // Strict mode must not turn repository-supplied click directives into links.
    await page.locator('#infra-source').fill('graph LR\n A[Safe] --> B[Node]\n click A "https://example.invalid/never"');
    await page.waitForFunction(() =>
      document.querySelector('#infra-view .diagram-status').dataset.state === 'ready'
      && document.querySelector('#infra-view svg')?.textContent.includes('Safe'));
    assert.equal(await page.locator('#infra-view svg a[href], #infra-view svg a[xlink\\:href]').count(), 0);

    if (screenshotDir && url.startsWith('file:')) {
      await fs.mkdir(screenshotDir, { recursive: true });
      await page.locator('#uml').screenshot({ path: path.join(screenshotDir, 'uml-offline.png') });
      await page.locator('#er').screenshot({ path: path.join(screenshotDir, 'er-offline.png') });
    }
    assert.deepEqual(externalRequests, [], 'The standalone portal must not request external resources');
    assert.deepEqual(pageErrors, [], 'Unexpected browser script errors');
    console.log(JSON.stringify({ mode: url.startsWith('file:') ? 'file-offline' : 'http-offline', diagrams: receipts,
      malformedSource: 'preserved', theme: 'redrawn', externalRequests: 0, pageErrors: 0 }));
  } finally {
    await context.close();
  }
}

(async () => {
  if (!process.argv[2]) throw new Error('Pass a generated index.html');
  const htmlPath = path.resolve(process.argv[2]);
  const content = await fs.readFile(htmlPath);
  const server = http.createServer((request, response) => {
    if (request.url !== '/') { response.writeHead(404).end(); return; }
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(content);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: process.env.BCK_ND_BROWSER_CHANNEL || undefined });
    await checkPage(browser, pathToFileURL(htmlPath).href, origin, process.argv[3]);
    await checkPage(browser, origin + '/', origin);
    const noScripts = await browser.newContext({ javaScriptEnabled: false, offline: true });
    const page = await noScripts.newPage();
    await page.goto(pathToFileURL(htmlPath).href);
    assert.equal(await page.locator('.diagram-status[data-state="pending"]').count(), 4);
    assert.equal(await page.locator('.diagram-canvas svg').count(), 0);
    assert(await page.locator('#uml-source').inputValue());
    await noScripts.close();
    console.log('JavaScript disabled: explicit explanation and complete source preserved');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

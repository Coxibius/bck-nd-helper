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

function largeClassDiagram() {
  const lines = ['classDiagram', '  direction LR'];
  for (let index = 0; index < 24; index += 1) {
    lines.push(`  class LargeClass${index} {`);
    for (let member = 0; member < 40; member += 1) {
      lines.push(`    +String field_${index}_${member}`);
    }
    lines.push('  }');
    if (index > 0) lines.push(`  LargeClass${index - 1} --> LargeClass${index}`);
  }
  return lines.join('\n');
}

function tallClassDiagram() {
  const lines = ['classDiagram', '  class TallService {'];
  for (let member = 0; member < 60; member += 1) {
    lines.push(`    +String field_${member}`);
  }
  lines.push('  }');
  return lines.join('\n');
}

async function diagramViewState(page, id) {
  return page.locator('#' + id + '-view').evaluate(view => {
    const scroll = view.querySelector('.diagram-scroll');
    const svg = view.querySelector('svg');
    const style = getComputedStyle(scroll);
    const rect = svg.getBoundingClientRect();
    const bounds = svg.viewBox.baseVal;
    const availableWidth = scroll.clientWidth
      - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const availableHeight = scroll.clientHeight
      - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    return {
      mode: view.dataset.zoomMode,
      label: view.querySelector('.diagram-controls output').textContent,
      scale: rect.width / bounds.width,
      fittingScale: Math.min(1, availableWidth / bounds.width, availableHeight / bounds.height),
      widthScale: availableWidth / bounds.width,
      heightScale: availableHeight / bounds.height,
      svgId: svg.id,
      viewerHeight: view.closest('.preview-pane').getBoundingClientRect().height,
    };
  });
}

async function dragViewerHeight(page, id, deltaY) {
  const pane = page.locator('#' + id + ' .preview-pane');
  await pane.evaluate(element => element.scrollIntoView({ block: 'end', inline: 'nearest' }));
  const before = await pane.boundingBox();
  assert(before, `${id}: viewer has no bounding box`);
  await page.mouse.move(before.x + before.width - 3, before.y + before.height - 3);
  await page.mouse.down();
  await page.mouse.move(
    before.x + before.width - 3,
    before.y + before.height - 3 + deltaY,
    { steps: 12 },
  );
  await page.mouse.up();
  await page.waitForFunction(({ id, beforeHeight, deltaY }) => {
    const current = document.querySelector('#' + id + ' .preview-pane')?.getBoundingClientRect().height;
    return current && Math.abs(current - beforeHeight) >= Math.min(40, Math.abs(deltaY) * 0.5);
  }, { id, beforeHeight: before.height, deltaY });
  await page.waitForFunction(id => {
    const view = document.getElementById(id + '-view');
    const scroll = view.querySelector('.diagram-scroll');
    return view.dataset.viewportSize === scroll.clientWidth + 'x' + scroll.clientHeight;
  }, id);
  const after = await pane.boundingBox();
  return { before: before.height, after: after.height };
}

async function observedDiagramPoint(page, id) {
  return page.locator('#' + id + '-view').evaluate(view => {
    const scroll = view.querySelector('.diagram-scroll');
    const svg = view.querySelector('svg');
    const scrollRect = scroll.getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    const scale = svgRect.width / svg.viewBox.baseVal.width;
    return {
      x: (scrollRect.left + scroll.clientWidth / 2 - svgRect.left) / scale,
      y: (scrollRect.top + scroll.clientHeight / 2 - svgRect.top) / scale,
      width: svg.viewBox.baseVal.width,
      height: svg.viewBox.baseVal.height,
    };
  });
}

function assertPointPreserved(before, after, action) {
  const toleranceX = Math.max(12, before.width * 0.03);
  const toleranceY = Math.max(12, before.height * 0.03);
  assert(Math.abs(before.x - after.x) <= toleranceX,
    `${action}: horizontal diagram point moved too far`);
  assert(Math.abs(before.y - after.y) <= toleranceY,
    `${action}: vertical diagram point moved too far`);
}

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

    await page.setViewportSize({ width: 1440, height: 1200 });
    await page.locator('#uml-source').fill(tallClassDiagram());
    await page.waitForFunction(() =>
      document.querySelector('#uml-view .diagram-status').dataset.state === 'ready'
      && document.querySelector('#uml-view svg')?.textContent.includes('TallService'));
    await page.locator('#uml').scrollIntoViewIfNeeded();
    const erHeight = await page.locator('#er .preview-pane').evaluate(pane => pane.getBoundingClientRect().height);
    const fitBeforeResize = await diagramViewState(page, 'uml');
    assert.equal(fitBeforeResize.mode, 'fit');
    assert.match(fitBeforeResize.label, /^Fit · /);
    assert(fitBeforeResize.heightScale < fitBeforeResize.widthScale,
      'the tall fixture must make Fit height-limited');
    const expanded = await dragViewerHeight(page, 'uml', 240);
    assert(expanded.after > expanded.before + 100 && expanded.after > 640,
      'native drag must expand the viewer beyond the old 640px ceiling');
    await page.waitForFunction(beforeScale => {
      const view = document.getElementById('uml-view');
      const svg = view.querySelector('svg');
      return view.dataset.zoomMode === 'fit'
        && svg.getBoundingClientRect().width / svg.viewBox.baseVal.width > beforeScale + 0.01;
    }, fitBeforeResize.scale);
    const fitAfterExpand = await diagramViewState(page, 'uml');
    assert.equal(fitAfterExpand.svgId, fitBeforeResize.svgId,
      'resizing must not regenerate Mermaid');
    assert(Math.abs(fitAfterExpand.scale - fitAfterExpand.fittingScale) <= 0.01,
      'Fit must track the expanded viewport');
    assert.equal(
      Math.round(await page.locator('#er .preview-pane').evaluate(pane => pane.getBoundingClientRect().height)),
      Math.round(erHeight),
      'resizing UML must not resize ER',
    );
    if (screenshotDir && url.startsWith('file:')) {
      await fs.mkdir(screenshotDir, { recursive: true });
      await page.locator('#uml').screenshot({ path: path.join(screenshotDir, 'uml-viewer-expanded.png') });
    }
    const reduced = await dragViewerHeight(page, 'uml', -140);
    assert(reduced.after < reduced.before - 60, 'native drag must also reduce viewer height');
    await page.waitForFunction(previousScale => {
      const svg = document.querySelector('#uml-view svg');
      return svg.getBoundingClientRect().width / svg.viewBox.baseVal.width < previousScale - 0.005;
    }, fitAfterExpand.scale);

    const largeUml = largeClassDiagram();
    await page.locator('#uml-source').fill(largeUml);
    await page.waitForFunction(() =>
      document.querySelector('#uml-view .diagram-status').dataset.state === 'ready'
      && document.querySelector('#uml-view svg')?.textContent.includes('LargeClass23'));
    await page.locator('#uml').scrollIntoViewIfNeeded();
    await page.getByRole('button', { name: 'uml diagram: actual', exact: true }).click();
    const manualState = await diagramViewState(page, 'uml');
    assert.equal(manualState.mode, 'manual');
    assert.match(manualState.label, /^Manual · 100\.0%$/);

    const scrollRegion = page.locator('#uml-view .diagram-scroll');
    const overflow = await scrollRegion.evaluate(scroll => ({
      horizontal: scroll.scrollWidth - scroll.clientWidth,
      vertical: scroll.scrollHeight - scroll.clientHeight,
    }));
    assert(overflow.horizontal > 100, 'large UML must create real horizontal scrolling');
    assert(overflow.vertical > 100, 'large UML must create real vertical scrolling');
    await scrollRegion.evaluate(scroll => {
      scroll.scrollLeft = (scroll.scrollWidth - scroll.clientWidth) * 0.55;
      scroll.scrollTop = (scroll.scrollHeight - scroll.clientHeight) * 0.55;
    });

    // Check the bar before clicking: Playwright must not rescue an inaccessible
    // control by scrolling it into view for the test.
    const toolbarState = await page.locator('#uml-view').evaluate(view => {
      const preview = view.closest('.preview-pane').getBoundingClientRect();
      const toolbar = view.querySelector('.diagram-controls').getBoundingClientRect();
      const scroll = view.querySelector('.diagram-scroll');
      return {
        scrollLeft: scroll.scrollLeft,
        scrollTop: scroll.scrollTop,
        visible: toolbar.top >= preview.top - 1 && toolbar.bottom <= preview.bottom + 1
          && toolbar.left >= preview.left - 1 && toolbar.right <= preview.right + 1,
      };
    });
    assert(toolbarState.scrollLeft > 0 && toolbarState.scrollTop > 0,
      'the diagram must be scrolled on both axes before checking the toolbar');
    assert(toolbarState.visible, 'the toolbar must remain visible inside its viewer while scrolling');
    assert.equal(await page.locator('.diagram-controls').count(), 4,
      'each diagram must have exactly one control bar');
    assert.equal(await page.locator('#uml-view .diagram-controls button').count(), 4);

    if (screenshotDir && url.startsWith('file:')) {
      await fs.mkdir(screenshotDir, { recursive: true });
      await page.locator('#uml').screenshot({ path: path.join(screenshotDir, 'uml-controls-scrolled.png') });
    }

    const beforeZoom = await observedDiagramPoint(page, 'uml');
    await page.getByRole('button', { name: 'uml diagram: in', exact: true }).click();
    const afterZoomIn = await observedDiagramPoint(page, 'uml');
    assertPointPreserved(beforeZoom, afterZoomIn, 'zoom in');
    await page.getByRole('button', { name: 'uml diagram: out', exact: true }).click();
    const afterZoomOut = await observedDiagramPoint(page, 'uml');
    assertPointPreserved(beforeZoom, afterZoomOut, 'zoom out');

    const manualBeforeResize = await diagramViewState(page, 'uml');
    const pointBeforeResize = await observedDiagramPoint(page, 'uml');
    const manualResize = await dragViewerHeight(page, 'uml', 120);
    assert(manualResize.after > manualResize.before + 50);
    await page.waitForFunction(previousHeight =>
      document.querySelector('#uml-view .diagram-scroll').clientHeight > previousHeight,
    manualResize.before - await page.locator('#uml-view .diagram-controls').evaluate(el => el.getBoundingClientRect().height));
    const manualAfterResize = await diagramViewState(page, 'uml');
    const pointAfterResize = await observedDiagramPoint(page, 'uml');
    assert.equal(manualAfterResize.mode, 'manual');
    assert(Math.abs(manualAfterResize.scale - manualBeforeResize.scale) <= 0.001,
      'manual resize must preserve the selected scale');
    assertPointPreserved(pointBeforeResize, pointAfterResize, 'manual viewer resize');

    await page.getByRole('button', { name: 'uml diagram: fit', exact: true }).click();
    const fitted = await page.locator('#uml-view').evaluate(view => {
      const scroll = view.querySelector('.diagram-scroll');
      const svg = view.querySelector('svg');
      const style = getComputedStyle(scroll);
      const availableWidth = scroll.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const availableHeight = scroll.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      const rect = svg.getBoundingClientRect();
      return { width: rect.width, height: rect.height, availableWidth, availableHeight,
        scrollLeft: scroll.scrollLeft, scrollTop: scroll.scrollTop };
    });
    assert(fitted.width <= fitted.availableWidth + 1 && fitted.height <= fitted.availableHeight + 1,
      'Fit must make the complete diagram visible');
    assert(fitted.scrollLeft <= 1 && fitted.scrollTop <= 1, 'Fit must restore the global view');
    assert.equal((await diagramViewState(page, 'uml')).mode, 'fit');

    await page.setViewportSize({ width: 480, height: 900 });
    await page.locator('#uml').scrollIntoViewIfNeeded();
    await page.locator('#uml .preview-pane').evaluate(pane => { pane.style.height = ''; });
    await page.getByRole('button', { name: 'uml diagram: fit', exact: true }).click();
    const narrow = await page.locator('#uml-view').evaluate(view => {
      const preview = view.closest('.preview-pane').getBoundingClientRect();
      const toolbar = view.querySelector('.diagram-controls').getBoundingClientRect();
      const buttons = [...view.querySelectorAll('.diagram-controls button')]
        .map(button => button.getBoundingClientRect());
      return {
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        toolbarInside: toolbar.left >= preview.left - 1 && toolbar.right <= preview.right + 1
          && toolbar.top >= preview.top - 1 && toolbar.bottom <= preview.bottom + 1,
        buttonsInside: buttons.every(rect => rect.left >= toolbar.left - 1 && rect.right <= toolbar.right + 1
          && rect.top >= toolbar.top - 1 && rect.bottom <= toolbar.bottom + 1),
      };
    });
    assert(narrow.pageOverflow <= 1, 'the SVG must not widen a narrow page');
    assert(narrow.toolbarInside && narrow.buttonsInside, 'narrow view must keep all controls accessible');
    const narrowExpanded = await dragViewerHeight(page, 'uml', 160);
    assert(narrowExpanded.after > narrowExpanded.before + 80,
      'native drag must expand the visible viewer in the narrow column layout');
    await page.getByRole('button', { name: 'uml diagram: in', exact: true }).click();
    assert.equal((await diagramViewState(page, 'uml')).mode, 'manual');
    await page.getByRole('button', { name: 'uml diagram: fit', exact: true }).click();
    assert.equal((await diagramViewState(page, 'uml')).mode, 'fit');
    const narrowAfterExpand = await page.locator('#uml-view').evaluate(view => {
      const preview = view.closest('.preview-pane').getBoundingClientRect();
      const toolbar = view.querySelector('.diagram-controls').getBoundingClientRect();
      const buttons = [...view.querySelectorAll('.diagram-controls button')]
        .map(button => button.getBoundingClientRect());
      return {
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        toolbarInside: toolbar.left >= preview.left - 1 && toolbar.right <= preview.right + 1
          && toolbar.top >= preview.top - 1 && toolbar.bottom <= preview.bottom + 1,
        buttonsInside: buttons.every(rect => rect.left >= toolbar.left - 1 && rect.right <= toolbar.right + 1
          && rect.top >= toolbar.top - 1 && rect.bottom <= toolbar.bottom + 1),
      };
    });
    assert(narrowAfterExpand.pageOverflow <= 1,
      'resizing the narrow viewer must not create horizontal page overflow');
    assert(narrowAfterExpand.toolbarInside && narrowAfterExpand.buttonsInside,
      'narrow controls must remain usable after resizing');
    if (screenshotDir && url.startsWith('file:')) {
      await page.locator('#uml').screenshot({
        path: path.join(screenshotDir, 'uml-viewer-narrow-resized.png'),
      });
    }
    const narrowReduced = await dragViewerHeight(page, 'uml', -120);
    assert(narrowReduced.after < narrowReduced.before - 60,
      'native drag must reduce a previously expanded narrow viewer');
    assert(narrowReduced.after >= 300, 'narrow viewer must preserve its minimum height');
    if (screenshotDir && url.startsWith('file:')) {
      await page.locator('#uml').screenshot({ path: path.join(screenshotDir, 'uml-controls-narrow.png') });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('#uml-source').fill(examples.uml);
    await page.waitForFunction(() =>
      document.querySelector('#uml-view .diagram-status').dataset.state === 'ready'
      && document.querySelector('#uml-view svg')?.textContent.includes('Admin'));

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
      narrowResize: { expanded: narrowExpanded, reduced: narrowReduced },
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

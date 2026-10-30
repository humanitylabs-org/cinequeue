// Managed CineQueue browser QA against a running container with FRESH (empty) data.
// Usage: NODE_PATH=<dir with playwright> node qa/browser_managed.cjs http://127.0.0.1:PORT/ [evidenceDir]
// Runs the full flow twice: at the container root, and behind a prefix-stripping proxy (/cinequeue/).
// Synthetic titles only; no network beyond the container; agent admission must be disabled.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');

const target = new URL(process.argv[2] || 'http://127.0.0.1:49230/');
const evidence = process.argv[3] || 'evidence';
const exe = process.env.CHROME_PATH || undefined;
fs.mkdirSync(evidence, { recursive: true });

function stripProxy(prefix) {
  // Mimics the App Manager / Caddy handle_path route: the app never sees the prefix.
  const server = http.createServer((req, res) => {
    if (!req.url.startsWith(prefix)) { res.writeHead(404); return res.end('outside prefix'); }
    const path = req.url.slice(prefix.length - 1) || '/';
    const up = http.request({ host: target.hostname, port: target.port, path, method: req.method,
      headers: { ...req.headers, host: `${target.hostname}:${target.port}` } }, (r) => {
      res.writeHead(r.statusCode, r.headers); r.pipe(res);
    });
    up.on('error', () => { res.writeHead(502); res.end(); });
    req.pipe(up);
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok(server)));
}

async function swipe(page, cdp, dx, dy = 3, steps = 14) {
  const row = page.locator('.movie').first();
  await row.scrollIntoViewIfNeeded();
  const box = await row.boundingBox();
  const x0 = box.x + box.width / 2, y0 = box.y + box.height / 2;
  const pt = (x, y) => ({ x, y, radiusX: 1, radiusY: 1, rotationAngle: 0, force: 0.8, id: 1 });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [pt(x0, y0)] });
  await page.waitForTimeout(30);
  for (let i = 1; i <= steps; i++) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [pt(x0 + dx * i / steps, y0 + dy * i / steps)] });
    await page.waitForTimeout(30);
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(700);
}

async function flow(browser, base, tag, apiBase) {
  const context = await browser.newContext({ viewport: { width: 393, height: 851 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  const api = async (p) => (await page.request.get(new URL(p, apiBase).href)).json();
  const titles = async () => page.locator('.movie h2').allTextContents();
  const shot = (n) => page.screenshot({ path: `${evidence}/${tag}-${n}.png` });
  const checks = [];

  await page.goto(base.href);
  await page.locator('.empty').waitFor();
  assert.equal(await page.locator('.empty').textContent(), 'No movies yet.');
  assert.equal((await api('api/config')).agent.ready, false);
  await shot('01-empty');
  checks.push('fresh install empty queue');

  // Add sheet in direct-add mode (no agent configured): honest copy, real cards.
  await page.locator('#addOpen').click();
  await page.locator('#addRequestPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#addRequestTitle').textContent(), 'Add a title');
  assert.equal(await page.locator('#addRequestButton').textContent(), 'Add to queue');
  // Back closes the sheet and stays in the app.
  await page.goBack();
  await page.locator('#addRequestPanel').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('.topbar').count(), 1);
  checks.push('Back closes add sheet, app stays open');
  await page.locator('#addOpen').click();
  await page.locator('#addRequestInput').fill(`${tag} Alpha 2001, ${tag} Beta 2002, ${tag} Gamma 2003`);
  await shot('02-add-sheet');
  await page.locator('#addRequestButton').click();
  await page.locator('#addRequestPanel').waitFor({ state: 'hidden' });
  await page.waitForFunction(() => document.querySelectorAll('.movie').length === 3);
  assert.equal((await api('api/movies')).movies.length, 3);
  checks.push('direct add via sheet persists 3 titles');
  await shot('03-queue');
  const order0 = await titles();

  // Detail (nested view) + Back returns to the list without leaving.
  const last = page.locator('.movie').last();
  const lastTitle = await last.locator('h2').textContent();
  await last.locator('.info').click();
  await page.locator('#detail:not(.hidden)').waitFor();
  assert.match(new URL(page.url()).pathname, /\/movie\//);
  assert.equal(await page.locator('.where-to-watch').count(), 0, 'where-to-watch hidden when no region configured');
  await shot('04-detail');
  await page.locator('.detail-bump').click();
  await page.waitForFunction((t) => document.querySelector('.detail-bump')?.textContent === 'Already at top' || false, lastTitle, { timeout: 5000 }).catch(() => {});
  await page.goBack();
  await page.locator('#detail.hidden').waitFor({ state: 'attached' });
  assert.equal(await page.locator('.topbar').count(), 1);
  assert.equal((await titles())[0], lastTitle, 'bumped title is first');
  checks.push('detail bump to top; Back from detail returns to list');

  // Deep link to a detail, then Back lands on the list (not out of the app).
  const firstId = (await api('api/movies')).movies[0].id;
  await page.goto(new URL(`movie/${encodeURIComponent(firstId)}`, base).href);
  await page.locator('#detail:not(.hidden)').waitFor();
  await page.goBack();
  await page.locator('#detail.hidden').waitFor({ state: 'attached' });
  assert.ok(page.url().startsWith(base.href), page.url());
  checks.push('deep-linked detail Back returns to root list');

  // Root Back floor: first Back shows the hint and stays; app still open.
  await page.goBack();
  await page.locator('#backHint').waitFor({ state: 'visible' });
  assert.ok(page.url().startsWith(base.href), page.url());
  assert.equal(await page.locator('.topbar').count(), 1);
  await shot('05-back-floor');
  checks.push('Back at the app start shows the shared stay-open hint');
  await page.waitForTimeout(2200);

  // Mark watched from detail, see history, then watch again.
  const watchTitle = (await titles())[0];
  await page.locator('.movie .info').first().click();
  await page.locator('.detail-watch').click();
  await page.waitForFunction(() => /again|Watch again/i.test(document.querySelector('.detail-watch')?.textContent || ''));
  let movie = (await api('api/movies')).movies.find((m) => m.title === watchTitle);
  assert.equal(movie.watch_history.length, 1);
  assert.equal(movie.queued, false);
  const hist = await api('api/history');
  assert.equal(hist.history[0].title, watchTitle);
  await shot('06-watched-detail');
  await page.goBack();
  await page.locator('[data-filter="watched"]').click();
  await page.waitForFunction((t) => [...document.querySelectorAll('.movie h2')].some((h) => h.textContent === t), watchTitle);
  await shot('07-watched-tab');
  await page.locator('.movie .info').first().click();
  const rewatch = page.locator('.detail-watch');
  assert.equal(await rewatch.textContent(), 'Watch again');
  await rewatch.click();
  await page.waitForFunction(() => document.querySelector('.detail-watch')?.textContent !== 'Adding…');
  movie = (await api('api/movies')).movies.find((m) => m.title === watchTitle);
  assert.equal(movie.queued, true);
  assert.equal(movie.watch_history.length, 1, 'rewatch keeps history');
  await page.goBack();
  await page.locator('[data-filter="unwatched"]').click();
  checks.push('mark watched, history feed, watched tab, rewatch keeps history');

  // Real CDP touch swipes: right = watched (+Undo), left = archive (+Undo), vertical = scroll only.
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  const ta = await page.evaluate(() => { const r = document.querySelector('.movie'); return [getComputedStyle(r).touchAction, getComputedStyle(r.querySelector('.movie-surface')).touchAction]; });
  assert.deepEqual(ta, ['pan-y', 'pan-y']);
  const rightId = await page.locator('.movie').first().getAttribute('data-movie-id');
  await swipe(page, cdp, 165);
  movie = (await api('api/movies')).movies.find((m) => m.id === rightId);
  assert.equal(movie.watched, true);
  assert.equal(await page.locator(`.movie[data-movie-id="${rightId}"]`).count(), 0);
  await page.locator('#undoButton').click();
  await page.waitForTimeout(400);
  movie = (await api('api/movies')).movies.find((m) => m.id === rightId);
  assert.equal(movie.queued, true);
  const leftId = await page.locator('.movie').first().getAttribute('data-movie-id');
  await swipe(page, cdp, -165);
  assert.equal((await api('api/movies?include_archived=1')).movies.find((m) => m.id === leftId).archived, true);
  await shot('08-archive-undo');
  await page.locator('#undoButton').click();
  await page.waitForTimeout(500);
  assert.equal((await api('api/movies')).movies.find((m) => m.id === leftId).archived, false);
  checks.push('CDP touch swipe right=watched/undo, left=archive/undo');

  // Restart-safe state is the server's; reload keeps queue and the in-app stack.
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll('.movie').length === 3);
  const manifest = await (await page.request.get(new URL('manifest.json', base).href)).json();
  assert.equal(manifest.start_url, './');
  assert.equal(manifest.display, 'standalone');
  assert.equal(await page.locator('script[src^="pwa-install.js"]').count(), 0);
  checks.push('reload persists; PWA manifest stays relative and Wizard owns installation');

  await page.setViewportSize({ width: 1280, height: 900 });
  await shot('09-desktop');
  assert.deepEqual(errors, []);
  await context.close();
  return { tag, base: base.href, order0, checks, errors };
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: exe });
  const results = [];
  try {
    results.push(await flow(browser, target, 'root', target));
    // Reset by archiving nothing: second pass uses its own titles through the prefix proxy.
    const proxy = await stripProxy('/cinequeue/');
    const prefixed = new URL(`http://127.0.0.1:${proxy.address().port}/cinequeue/`);
    // The prefix pass needs an empty queue too: archive the root pass titles via the API first.
    const ids = (await (await fetch(new URL('api/movies', target))).json()).movies.map((m) => m.id);
    for (const id of ids) await fetch(new URL(`api/archive/${encodeURIComponent(id)}`, target), { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
    results.push(await flow(browser, prefixed, 'prefix', prefixed));
    proxy.close();
  } finally {
    await browser.close();
  }
  fs.writeFileSync(`${evidence}/browser-managed.json`, JSON.stringify({ pass: true, results }, null, 2));
  console.log('BROWSER_MANAGED_OK', results.map((r) => `${r.tag}:${r.checks.length}`).join(' '));
})().catch((e) => { console.error(e); process.exit(1); });

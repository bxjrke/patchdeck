// Optional browser regression checks. Run against the disposable demo app only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;

const base = process.argv[2] || 'http://127.0.0.1:8765';
const artifacts = process.env.PATCHDECK_UI_ARTIFACTS || fs.mkdtempSync(path.join(os.tmpdir(), 'patchdeck-ui-'));
const headers = {'X-Patchdeck-Request': '1'};

(async () => {
  fs.mkdirSync(artifacts, {recursive: true});
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 390, height: 844}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const health = await page.request.get(base + '/healthz');
    assert.equal((await health.json()).mode, 'demo', 'UI checks must target the disposable demo, never production');
  } catch (error) {
    await browser.close();
    throw error;
  }
  const originalSettings = await (await page.request.get(base + '/api/settings')).json();
  const originalServices = await (await page.request.get(base + '/api/services')).json();
  const servicePath = id => base + '/api/services/' + encodeURIComponent(id);
  try {
    await page.request.patch(base + '/api/settings', {headers, data: {language: 'en', theme: 'system'}});
    const layouts = [];
    for (const language of ['en', 'de']) {
      await page.request.patch(base + '/api/settings', {headers, data: {language}});
    for (const scheme of ['light', 'dark']) {
      await page.emulateMedia({colorScheme: scheme});
      for (const width of [320, 390, 768, 1440]) {
        await page.setViewportSize({width, height: 900});
        for (const route of ['/', '/settings']) {
          await page.goto(base + route);
          await page.waitForSelector(route === '/' ? '#services .card' : '.service-config');
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
          if (width === 320) {
            await page.evaluate(() => document.documentElement.style.fontSize = '200%');
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${language} ${scheme} ${width} ${route}: 200% text must reflow`);
            await page.evaluate(() => document.documentElement.style.fontSize = '');
          }
          if (width === 390) {
            const report = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
            assert.deepEqual(report.violations.map(item => ({id: item.id, targets: item.nodes.map(node => node.target)})), [], route + ' accessibility');
            await page.screenshot({path: path.join(artifacts, `${route === '/' ? 'home' : 'settings'}-${language}-${scheme}.png`), fullPage: true});
          }
          layouts.push({language, scheme, width, route});
        }
      }
    }

    }
    await page.request.patch(base + '/api/settings', {headers, data: {language: 'en'}});
    await page.setViewportSize({width: 390, height: 844});
    await page.goto(base + '/settings');
    await page.waitForSelector('.service-config');
    // Stable switch names, field errors, and confirmations that do not expire.
    await page.getByRole('switch', {name: 'Enable MQTT', exact: true}).check();
    await page.waitForFunction(() => document.querySelector('#settings-save-status').dataset.state === 'saved');
    assert.equal(await page.locator('#mqtt-fields').isVisible(), true);
    let writes = 0;
    page.on('request', request => {
      if (new URL(request.url()).pathname === '/api/settings' && request.method() === 'PATCH') writes++;
    });
    await page.locator('#update-interval').fill('0');
    await page.waitForTimeout(650);
    assert.equal(writes, 0, 'Invalid fields must not be submitted');
    assert.equal(await page.locator('#update-interval').getAttribute('aria-invalid'), 'true');
    assert.match(await page.locator('#update-interval-error').innerText(), /1.*10080/);
    const save = page.waitForResponse(response => response.url().endsWith('/api/settings') && response.request().method() === 'PATCH');
    await page.locator('#update-interval').fill('60');
    await page.locator('#update-interval').blur();
    assert.equal((await save).status(), 200);
    await page.waitForFunction(() => document.querySelector('#settings-save-status').dataset.state === 'saved');
    await page.waitForTimeout(2200);
    assert.equal(await page.locator('#settings-save-status').isVisible(), true);

    // Full configuration restoration, even if deletion races with an autosave.
    const originalGrocy = originalServices.find(service => service.id === 'grocy');
    assert.ok(originalGrocy, 'Demo fixture Grocy is required');
    const fixture = {...originalGrocy, compose_file: '/demo/compose.yaml', metadata: {demo_note: 'preserve this'}};
    await page.request.put(servicePath('grocy'), {headers, data: fixture});
    await page.reload();
    await page.locator('[data-action="toggle-service-settings"][data-service-id="grocy"]').click();
    let releaseSave;
    const pendingSave = new Promise(resolve => { releaseSave = resolve; });
    let sawSave;
    const saveStarted = new Promise(resolve => { sawSave = resolve; });
    await page.route('**/api/services/grocy', async route => {
      if (route.request().method() === 'PUT') {
        sawSave();
        await pendingSave;
      }
      await route.continue();
    });
    await page.locator('#edit-name-grocy').fill('Grocy edited');
    await page.locator('#edit-name-grocy').blur();
    await saveStarted;
    await page.locator('[data-action="delete-service"][data-service-id="grocy"]').click();
    releaseSave();
    await page.waitForSelector('[data-action="undo-delete-service"][data-service-id="grocy"]');
    await page.unroute('**/api/services/grocy');
    assert.equal((await (await page.request.get(base + '/api/services')).json()).some(service => service.id === 'grocy'), false);
    await page.getByRole('button', {name: 'Undo: Grocy edited', exact: true}).click();
    await page.waitForSelector('[data-service-config="grocy"]');
    const restored = (await (await page.request.get(base + '/api/services')).json()).find(service => service.id === 'grocy');
    assert.equal(restored.name, 'Grocy edited');
    assert.equal(restored.compose_file, fixture.compose_file);
    assert.deepEqual(restored.metadata, fixture.metadata);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.action), 'toggle-service-settings');

    // A conflicting ID must leave the current service intact, with Undo still available.
    await page.locator('[data-action="delete-service"][data-service-id="grocy"]').click();
    await page.waitForSelector('[data-action="undo-delete-service"][data-service-id="grocy"]');
    await page.locator('[data-action="delete-service"][data-service-id="mosquitto"]').click();
    await page.waitForSelector('[data-action="undo-delete-service"][data-service-id="mosquitto"]');
    assert.equal(await page.locator('[data-action="undo-delete-service"]').count(), 2);
    await page.locator('[data-action="undo-delete-service"][data-service-id="mosquitto"]').click();
    await page.waitForSelector('[data-service-config="mosquitto"]');
    assert.equal(await page.locator('[data-action="undo-delete-service"]').count(), 1);
    await page.request.put(servicePath('grocy'), {headers, data: {...fixture, name: 'Existing configuration'}});
    await page.locator('[data-action="undo-delete-service"][data-service-id="grocy"]').click();
    await page.waitForSelector('[data-undo-error]:not([hidden])');
    assert.match(await page.locator('[data-undo-error]').innerText(), /already in use/);
    assert.equal((await (await page.request.get(base + '/api/services')).json()).find(service => service.id === 'grocy').name, 'Existing configuration');
    assert.equal(await page.locator('[data-action="undo-delete-service"][data-service-id="grocy"]').isEnabled(), true);
    await page.request.delete(servicePath('grocy'), {headers});
    await page.route('**/api/services/grocy', route => route.request().method() === 'PUT' ? route.fulfill({status: 503, body: '{}'}) : route.continue());
    await page.locator('[data-action="undo-delete-service"][data-service-id="grocy"]').click();
    await page.waitForFunction(() => document.querySelector('[data-undo-error]').textContent.includes('Could not restore'));
    assert.equal(await page.locator('[data-action="undo-delete-service"][data-service-id="grocy"]').isEnabled(), true);
    await page.unroute('**/api/services/grocy');
    await page.locator('[data-action="undo-delete-service"][data-service-id="grocy"]').click();
    await page.waitForSelector('[data-service-config="grocy"]');

    await page.goto(base);
    await page.waitForSelector('#services .card');
    assert.equal(await page.locator('.service-state .badge[data-action]').count(), 0, 'Status labels must not act as buttons');
    assert.equal(await page.locator('#update-all').isVisible(), true, 'Restart the demo to restore update fixtures before running checks');
    await page.locator('#update-all').click();
    await page.waitForSelector('.is-updating progress');
    await page.waitForSelector('.is-queued .queue-notice');
    const active = page.locator('.is-updating').first();
    assert.ok((await active.locator('progress').getAttribute('aria-label')).includes(await active.locator('h2').innerText()));
    assert.equal(await page.locator('.is-queued progress').count(), 0, 'Queued services must not look active');
    await page.waitForFunction(() => document.querySelector('#update-all').hidden, {}, {timeout: 20000});
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(artifacts, 'results.json'), JSON.stringify({layouts, uncaughtErrors: errors, checks: 'Axe AA, text enlargement, stable labels, inline validation, persistent feedback, autosave/delete ordering, full undo, conflict handling, focus restoration, separate status/actions'}, null, 2));
    console.log(`PASS: ${layouts.length} layouts, Axe AA, HIG interaction checks. Artifacts: ${artifacts}`);
  } finally {
    for (const service of originalServices) await page.request.put(servicePath(service.id), {headers, data: service});
    await page.request.patch(base + '/api/settings', {headers, data: originalSettings});
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

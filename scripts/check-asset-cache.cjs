// Reproduce an upgrade with legacy language/icon files still fresh in the browser cache.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {once} = require('node:events');
const browsers = require('playwright');

const upstream = new URL(process.argv[2] || 'http://127.0.0.1:8767');
const expectStale = process.argv.includes('--expect-stale');
const engine = process.env.PATCHDECK_BROWSER || 'chromium';
const staticRoot = path.join(__dirname, '../src/patchdeck/static');
const translations = Object.fromEntries(['en', 'de'].map(language => [language,
  JSON.parse(fs.readFileSync(path.join(staticRoot, 'i18n', language + '.json'), 'utf8')),
]));
const legacy = new Map();
for (const language of ['en', 'de']) {
  const values = {...translations[language]};
  for (const key of ['settingsIntro', 'enableMqtt', 'mqttHelp']) delete values[key];
  legacy.set('/static/i18n/' + language + '.json', JSON.stringify(values));
}
legacy.set('/static/icons.svg', fs.readFileSync(path.join(staticRoot, 'icons.svg'), 'utf8')
  .replace(/<symbol id="arrow-left"[\s\S]*?<\/symbol>/, ''));

(async () => {
  let prime = true;
  const requests = [];
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, upstream);
    requests.push(url.pathname + url.search);
    if (url.pathname === '/cache-prime') {
      response.writeHead(200, {'Content-Type': 'text/html'});
      response.end('<!doctype html><title>Cache fixture</title>');
      return;
    }
    if (prime && legacy.has(url.pathname)) {
      response.writeHead(200, {
        'Content-Type': url.pathname.endsWith('.svg') ? 'image/svg+xml' : 'application/json',
        'Cache-Control': 'public, max-age=31536000',
      });
      response.end(legacy.get(url.pathname));
      return;
    }
    const proxy = http.request(url, {method: request.method, headers: {...request.headers, host: upstream.host}}, result => {
      response.writeHead(result.statusCode, result.headers);
      result.pipe(response);
    });
    proxy.on('error', error => { response.writeHead(502); response.end(error.message); });
    request.pipe(proxy);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  let browser;
  let page;
  let origin;
  let originalSettings;
  try {
    assert.ok(['chromium', 'webkit'].includes(engine), 'Unsupported browser engine');
    browser = await browsers[engine].launch({headless: true});
    const context = await browser.newContext({viewport: {width: 393, height: 852}, isMobile: true, hasTouch: true, colorScheme: 'dark'});
    page = await context.newPage();
    origin = 'http://127.0.0.1:' + server.address().port;
    const health = await page.request.get(origin + '/healthz');
    assert.equal((await health.json()).mode, 'demo', 'Cache checks require the disposable test fixture');
    originalSettings = await (await page.request.get(origin + '/api/settings')).json();
    await page.request.patch(origin + '/api/settings', {headers: {'X-Patchdeck-Request': '1'}, data: {language: 'de'}});
    await page.goto(origin + '/cache-prime');
    await page.evaluate(async () => {
      for (const resource of ['/static/i18n/en.json', '/static/i18n/de.json', '/static/icons.svg']) {
        const response = await fetch(resource);
        if (!response.ok) throw new Error(resource);
        await response.text();
      }
    });
    prime = false;
    requests.length = 0;
    await page.goto(origin + '/settings');
    await page.waitForSelector('.service-config');
    const keys = ['settingsIntro', 'enableMqtt', 'mqttHelp'];
    const labels = await Promise.all(keys.map(key => page.locator('[data-i18n="' + key + '"]').innerText()));
    const icon = page.locator('.settings-link svg use');
    await page.waitForTimeout(150);
    const iconWidth = await icon.evaluate(node => node.getBBox().width);
    if (expectStale) {
      assert.deepEqual(labels, keys, 'Expected the cached legacy dictionaries to reproduce raw keys');
      assert.equal(iconWidth, 0, 'Expected the old sprite to be missing the back arrow');
      console.log('REPRODUCED: stale translations and missing back icon after upgrade (' + engine + ')');
    } else {
      assert.deepEqual(labels, keys.map(key => translations.de[key]));
      await page.waitForFunction(() => document.querySelector('.settings-link svg use').getBBox().width > 0);
      const sprite = await icon.getAttribute('href');
      const currentVersion = await page.locator('html').getAttribute('data-asset-version');
      assert.ok(currentVersion, 'Page must identify its browser asset version');
      assert.equal(new URL(sprite, origin).search.slice(1), currentVersion);
      assert.equal(new URL(sprite, origin).hash, '#arrow-left');
      for (const language of ['en', 'de']) {
        assert.ok(requests.includes('/static/i18n/' + language + '.json?' + currentVersion), 'Versioned dictionary must bypass the legacy cache');
      }
      await page.getByRole('switch', {name: translations.de.enableMqtt, exact: true}).check();
      await page.waitForSelector('#mqtt-fields:not([hidden])');
      assert.equal(await page.locator('#mqtt-toggle-label').innerText(), translations.de.enableMqtt);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      console.log('PASS: warm-cache upgrade renders German copy, back arrow and MQTT correctly (' + engine + ')');
    }
  } finally {
    if (page && originalSettings) await page.request.patch(origin + '/api/settings', {headers: {'X-Patchdeck-Request': '1'}, data: originalSettings});
    if (browser) await browser.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

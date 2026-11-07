/* Browser acceptance test: real local server, real public providers, no fixtures. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const output = process.env.CONTROL_ROOM_ARTIFACTS || 'control-room-browser-artifacts';
fs.mkdirSync(output, { recursive: true });
const diagnostics = { console: [], page_errors: [], responses: [], accepted: false };
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
page.on('console', message => diagnostics.console.push({ type: message.type(), text: message.text() }));
page.on('pageerror', error => diagnostics.page_errors.push(String(error)));
page.on('response', async response => {
  if (response.url().includes('/api/snapshot')) {
    const item = { url: response.url(), status: response.status() };
    try { item.body = await response.json(); } catch { item.body = 'NON_JSON'; }
    diagnostics.responses.push(item);
  }
});

try {
  await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle', timeout: 30_000 });
  await page.waitForFunction(() => document.querySelector('[data-testid="source-status"]')?.textContent === 'PUBLIC_NO_AUTH', null, { timeout: 30_000 });
  const venues = await page.locator('[data-testid="venue-evidence"]').textContent();
  const permissions = await page.locator('[data-testid="trading-permissions"]').textContent();
  if (!venues.includes('BINANCE') || !venues.includes('KRAKEN')) throw new Error('Missing live Binance/Kraken evidence in rendered page');
  if (permissions !== 'Trading permissions: disabled') throw new Error(`Unsafe rendered permissions: ${permissions}`);
  const painted = await page.locator('[data-testid="candles"]').evaluate(canvas => {
    const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] !== 7 || data[i + 1] !== 16 || data[i + 2] !== 26) return true;
    }
    return false;
  });
  if (!painted) throw new Error('Candles canvas was not rendered');
  const live = diagnostics.responses.at(-1)?.body;
  if (!live || live.orders_enabled !== false || live.candles?.length !== 80 ||
      new Set(live.evidence.map(item => item.source)).size !== 2) {
    throw new Error('Live snapshot does not satisfy Control Room acceptance contract');
  }
  diagnostics.accepted = true;
  await page.screenshot({ path: path.join(output, 'control-room-live.png'), fullPage: true });
} finally {
  fs.writeFileSync(path.join(output, 'browser-diagnostics.json'), JSON.stringify(diagnostics, null, 2));
  await browser.close();
}
if (!diagnostics.accepted) process.exitCode = 1;

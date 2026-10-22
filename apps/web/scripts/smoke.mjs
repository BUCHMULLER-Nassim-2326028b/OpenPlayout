// Optional smoke test against a running local app; uses an installed Chrome.
import { chromium } from 'playwright-core';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const token = process.env.OPENPLAYOUT_API_TOKEN || (await readFile(path.join(root, 'data/api-token'), 'utf8')).trim();
const executablePath = process.env.OPENPLAYOUT_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({executablePath, headless: true});
const errors = [];
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1050}});
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(process.env.OPENPLAYOUT_URL || 'http://127.0.0.1:8000');
  await page.getByLabel('Local API token').fill(token);
  await page.getByRole('button', {name: 'Open control room'}).click();
  await page.getByRole('heading', {name: 'Control room'}).waitFor();
  await page.getByText('Live status connected', {exact: true}).waitFor();
  await page.getByRole('heading', {name: 'Your rundown is empty'}).waitFor();
  await page.getByRole('link', {name: 'Media library', exact: true}).click();
  await page.getByRole('heading', {name: 'Media library'}).waitFor();
  await page.getByLabel('Search media').fill('no-such-test-asset');
  await page.getByRole('heading', {name: 'No media found'}).waitFor();
  await page.getByRole('link', {name: 'Settings', exact: true}).click();
  await page.getByLabel('AMCP host', {exact: true}).waitFor();
  await page.getByRole('heading', {name: 'Read-only media directories'}).waitFor();
  await page.getByRole('link', {name: 'Control room', exact: true}).click();
  await mkdir(path.join(root, '.tools/screenshots'), {recursive: true});
  await page.screenshot({path: path.join(root, '.tools/screenshots/control-room.png'), fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  await page.getByRole('heading', {name: 'Control room'}).waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  if (overflow) throw new Error('Mobile layout overflows the viewport');
  await page.setViewportSize({width: 1440, height: 1050});
  await page.getByRole('button', {name: 'Lock interface'}).click();
  await page.getByLabel('Local API token').waitFor();
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('Browser smoke passed: unlock, WebSocket, control room, library, settings, mobile width, lock.');
} finally {
  await browser.close();
}

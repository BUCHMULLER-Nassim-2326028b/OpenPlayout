// Run against an isolated acceptance database with synthetic indexed media.
import { chromium } from 'playwright-core';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const token = process.env.OPENPLAYOUT_API_TOKEN || (await readFile(path.join(root, 'data/api-token'), 'utf8')).trim();
const browser = await chromium.launch({executablePath: process.env.OPENPLAYOUT_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1050}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(process.env.OPENPLAYOUT_URL || 'http://127.0.0.1:8000');
  await page.getByLabel('Local API token').fill(token);
  await page.getByRole('button', {name: 'Open control room'}).click();
  await page.getByRole('link', {name: 'Schedule', exact: true}).click();
  await page.getByLabel('New schedule name').fill(`Browser acceptance ${Date.now()}`);
  await page.getByRole('button', {name: 'Create', exact: true}).click();
  await page.getByRole('heading', {name: 'Add event', exact: true}).waitFor();
  const option = await page.getByLabel('Media', {exact: true}).locator('option').nth(1).getAttribute('value');
  if (!option) throw new Error('Schedule browser test requires indexed synthetic media');
  await page.getByLabel('Media', {exact: true}).selectOption(option);
  await page.getByLabel('Event label').fill('Fixed morning program');
  await page.getByLabel('Local start time').fill('2030-01-01T10:00');
  await page.getByRole('button', {name: 'Add event', exact: true}).click();
  await page.locator('.schedule-event-row').first().waitFor();
  await page.getByLabel('Time constraint').selectOption('soft');
  await page.getByLabel('Event label').fill('Flexible follow-up');
  await page.getByRole('button', {name: 'Add event', exact: true}).click();
  await page.getByText('Moved later by 3 seconds', {exact: true}).waitFor();
  await page.getByLabel('Local date', {exact: true}).fill('2030-01-01');
  await page.locator('.schedule-block').first().waitFor();
  const block = page.locator('.schedule-block.hard');
  const bounds = await block.boundingBox();
  if (!bounds) throw new Error('Timeline block is not visible');
  await page.mouse.move(bounds.x + 5, bounds.y + 10);
  await page.mouse.down();
  await page.mouse.move(bounds.x + 35, bounds.y + 10, {steps: 10});
  await page.mouse.up();
  // The hard event moved later, freeing the soft event's originally requested slot.
  await page.getByText('Moved later by 3 seconds', {exact: true}).waitFor({state: 'hidden'});
  const download = page.waitForEvent('download');
  await page.getByRole('button', {name: 'JSON', exact: true}).click();
  if (!(await download).suggestedFilename().endsWith('.json')) throw new Error('Schedule export failed');
  await mkdir(path.join(root, '.tools/screenshots'), {recursive: true});
  await page.screenshot({path: path.join(root, '.tools/screenshots/schedule.png'), fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Schedule layout overflows on mobile');
  await page.reload();
  await page.getByRole('heading', {name: 'Schedule', exact: true}).waitFor();
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('Schedule browser smoke passed: create, hard/soft placement, timeline drag, JSON export, mobile layout, reload.');
} finally {
  await browser.close();
}

// End-to-end smoke of the CSV flow against a running stack (api + worker + vite).
// Usage: BROWSER=/path/to/chromium node e2e/csv-smoke.mjs <file.csv> [outDir]
// Uploads the file, asks a question that needs a computed total, clicks citation 1. Asserts the cited cells are
// washed, the margin pin "1" sits in the first cited row's gutter, the row is scrolled into view under the sticky
// header, and the region stepper walks the cells read; then find, light theme, zoom and mobile. Saves screenshots.
import { chromium } from 'playwright-core'

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
const [file, out = '.'] = process.argv.slice(2)
if (!file) throw new Error('usage: node e2e/csv-smoke.mjs <file.csv> [outDir]')
const question = process.env.QUESTION ?? 'What is the sum of Units for West?'
const shot = (page, name) => page.screenshot({ path: `${out}/${name}.png` })
const inView = (loc) =>
  loc.evaluate((el) => {
    const box = el.getBoundingClientRect()
    const view = el.closest('.ad-viewer').getBoundingClientRect()
    const head = el.closest('.ad-csv-grid').querySelector('.ad-csv-head').getBoundingClientRect()
    return box.top >= head.bottom - 1 && box.bottom <= view.bottom
  })
const rowOf = (loc) => loc.evaluate((el) => el.closest('[role=row]').getAttribute('aria-rowindex'))

const browser = await chromium.launch({ executablePath: process.env.BROWSER, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
await page.goto(`${BASE}/#/`)
await page.getByRole('heading', { level: 1 }).waitFor()
await page.locator('input[type=file]').setInputFiles(file)

const composer = page.getByRole('textbox', { name: 'Ask about this document' })
await composer.waitFor()
await page.waitForFunction(() => !document.querySelector('textarea')?.disabled, null, { timeout: 120_000 })
await page.locator('.ad-csv-grid').waitFor({ timeout: 30_000 })
const rendered = await page.locator('.ad-csv-row').count()
if (rendered > 80) throw new Error(`grid should be virtualised, rendered ${rendered} rows`)
await shot(page, 'c1-new-conversation')

await composer.fill(question)
await page.keyboard.press('Enter')
const firstCite = page.getByRole('button', { name: /^Citation 1, / }).first()
await firstCite.waitFor({ timeout: 120_000 })
await page.waitForFunction(() => !document.querySelector('[aria-busy=true]'), null, { timeout: 120_000 })
const citeLabel = await firstCite.getAttribute('aria-label')
await firstCite.click()

const pin = page.locator('.ad-csv-pin').first()
await pin.waitFor({ timeout: 10_000 })
await page.waitForTimeout(400)
if ((await pin.textContent()) !== '1') throw new Error('pin label should match citation number 1')
const hits = page.locator('[data-hit=evidence]')
if (!(await hits.count())) throw new Error('no cited cells washed')
const firstHit = hits.first()
if (!(await inView(firstHit))) throw new Error('first cited cell is not in view below the header')
if ((await rowOf(pin)) !== (await rowOf(firstHit))) throw new Error('pin is not in the first cited row')
await shot(page, 'c2-cited')

const stepper = page.getByLabel('Evidence locations')
if (await stepper.count()) {
  const before = await page.locator('.ad-csv').evaluate((el) => el.scrollTop)
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Next evidence location' }).click()
  await page.waitForTimeout(300)
  const after = await page.locator('.ad-csv').evaluate((el) => el.scrollTop)
  if (after === before) console.warn('stepper: regions 1-4 all fit in one screen (no scroll)')
  if (!(await inView(page.locator('[data-hit=evidence]').last()))) console.warn('stepper: last washed cell off screen')
  await shot(page, 'c3-stepped')
}

await page.getByRole('textbox', { name: 'Find in document' }).fill(process.env.FIND ?? 'warranty')
await page.keyboard.press('Enter')
const found = page.locator('[data-find=current]')
await found.waitFor({ timeout: 5_000 })
if (!(await inView(found))) throw new Error('current find match is not in view')
await shot(page, 'c4-find')

await page.getByRole('button', { name: 'Light theme' }).click()
await page.waitForTimeout(300)
await firstCite.click()
await page.waitForTimeout(400)
await shot(page, 'c5-light')
await page.getByRole('button', { name: 'Zoom in' }).click()
await page.getByRole('button', { name: 'Zoom in' }).click()
await page.waitForTimeout(300)
await firstCite.click()
await page.waitForTimeout(400)
if ((await rowOf(page.locator('.ad-csv-pin').first())) !== (await rowOf(page.locator('[data-hit=evidence]').first())))
  throw new Error('pin left its row after zoom')
await shot(page, 'c6-zoomed')
await page.getByRole('button', { name: 'Dark theme' }).click()

await page.setViewportSize({ width: 390, height: 844 })
await page.waitForTimeout(600)
await shot(page, 'c7-mobile')
if (errors.length) throw new Error(`page errors: ${errors.join('; ')}`)
console.log(`OK: ${citeLabel}; ${await hits.count()} cells washed`)
await browser.close()

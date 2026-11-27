// End-to-end smoke of the DOCX flow against a running stack (api + worker + vite).
// Usage: BROWSER=/path/to/chromium node e2e/docx-smoke.mjs <file.docx> [outDir]
// Uploads the file, asks a question, clicks citation 1. Asserts the cited paragraph is washed, the exact quote is
// painted (CSS Highlight API), the margin pin shows "1" beside it, and it is scrolled into view; then find, light
// theme, zoom and mobile. Saves screenshots.
import { chromium } from 'playwright-core'

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
const [file, out = '.'] = process.argv.slice(2)
if (!file) throw new Error('usage: node e2e/docx-smoke.mjs <file.docx> [outDir]')
const question = process.env.QUESTION ?? 'What monthly fee does Harbor Lane Logistics pay?'
const shot = (page, name) => page.screenshot({ path: `${out}/${name}.png` })
const inView = (loc) =>
  loc.evaluate((el) => {
    const box = el.getBoundingClientRect()
    const view = el.closest('.ad-viewer').getBoundingClientRect()
    return box.top >= view.top && box.bottom <= view.bottom
  })

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
await page.locator('.ad-docx section.docx').first().waitFor({ timeout: 30_000 })
await page.getByText('What would you like to know?').waitFor()
await shot(page, 'd1-new-conversation')

await composer.fill(question)
await page.keyboard.press('Enter')
const firstCite = page.getByRole('button', { name: /^Citation 1, (paragraphs?|table) / }).first()
await firstCite.waitFor({ timeout: 120_000 })
await page.waitForFunction(() => !document.querySelector('[aria-busy=true]'), null, { timeout: 120_000 })
await firstCite.click()

const pin = page.locator('.ad-docx-pin').first()
await pin.waitFor({ timeout: 10_000 })
await page.waitForTimeout(500)
if ((await pin.textContent()) !== '1') throw new Error('pin label should match citation number 1')
const hit = page.locator('.ad-docx-hit').first()
if (!(await hit.count())) throw new Error('no cited paragraph washed')
if (!(await inView(hit))) throw new Error('cited paragraph is not scrolled into view')
const citeLabel = await firstCite.getAttribute('aria-label')
const painted = await page.evaluate(() => {
  const h = CSS.highlights?.get('ad-evidence')
  return h ? [...h].map((r) => r.toString()) : []
})
if (!painted.length || !painted.every((t) => t.trim())) throw new Error(`quote not painted: ${JSON.stringify(painted)}`)
const pinBox = await pin.boundingBox()
const hitBox = await hit.boundingBox()
if (Math.abs(pinBox.y - hitBox.y) > 4) throw new Error(`pin at y=${pinBox.y}, paragraph at y=${hitBox.y}`)
if (pinBox.x >= hitBox.x) throw new Error('pin should sit in the margin left of the paragraph')
await shot(page, 'd2-cited')

await page.getByRole('textbox', { name: 'Find in document' }).fill(process.env.FIND ?? 'platform')
await page.keyboard.press('Enter')
await page.waitForFunction(() => CSS.highlights?.get('ad-find-current')?.size === 1, null, { timeout: 5_000 })
await shot(page, 'd3-find')

await page.getByRole('button', { name: 'Light theme' }).click()
await page.waitForTimeout(300)
await firstCite.click()
await page.waitForTimeout(500)
await shot(page, 'd4-light')
await page.getByRole('button', { name: 'Zoom in' }).click()
await page.getByRole('button', { name: 'Zoom in' }).click()
await page.waitForTimeout(300)
await firstCite.click()
await page.waitForTimeout(500)
const zPin = await page.locator('.ad-docx-pin').first().boundingBox()
const zHit = await page.locator('.ad-docx-hit').first().boundingBox()
if (Math.abs(zPin.y - zHit.y) > 4) throw new Error('pin drifted from its paragraph after zoom')
await shot(page, 'd5-zoomed')
await page.getByRole('button', { name: 'Dark theme' }).click()

await page.setViewportSize({ width: 390, height: 844 })
await page.waitForTimeout(600)
await shot(page, 'd6-mobile')
if (errors.length) throw new Error(`page errors: ${errors.join('; ')}`)
console.log(`OK: ${citeLabel}; painted ${JSON.stringify(painted)}`)
await browser.close()

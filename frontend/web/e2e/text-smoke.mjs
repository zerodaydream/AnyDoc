// End-to-end smoke of the TXT/Markdown flow against a running stack (api + worker + vite).
// Usage: BROWSER=/path/to/chromium node e2e/text-smoke.mjs <file.md|file.txt> [outDir]
// Uploads the file, asks a question, clicks citation 1. Markdown opens in Preview: asserts the cited block is
// washed and pinned in view, then switches to the Markdown source. In source view asserts the evidence is marked
// on the cited lines, the margin pin shows "1" and the evidence is scrolled into view. Saves screenshots.
import { chromium } from 'playwright-core'

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
const [file, out = '.'] = process.argv.slice(2)
if (!file) throw new Error('usage: node e2e/text-smoke.mjs <file.md|file.txt> [outDir]')
const question = process.env.QUESTION ?? 'Which helper is used to define the storage in the persist middleware example?'
const shot = (page, name) => page.screenshot({ path: `${out}/${name}.png` })
const markdown = /\.(md|markdown)$/i.test(file)
const inView = (loc) =>
  loc.evaluate((el) => {
    const box = el.getBoundingClientRect()
    const view = el.closest('.ad-viewer').getBoundingClientRect()
    return box.top >= view.top && box.bottom <= view.bottom
  })

const browser = await chromium.launch({ executablePath: process.env.BROWSER, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
page.on('pageerror', (e) => console.error('pageerror:', e.message))
await page.goto(`${BASE}/#/`)
await page.getByRole('heading', { level: 1 }).waitFor()
await page.locator('input[type=file]').setInputFiles(file)

const composer = page.getByRole('textbox', { name: 'Ask about this document' })
await composer.waitFor()
await page.waitForFunction(() => !document.querySelector('textarea')?.disabled, null, { timeout: 120_000 })
await page.locator(markdown ? '.ad-md' : '.ad-sheet .ad-tl').first().waitFor({ timeout: 30_000 })
await page.getByText('What would you like to know?').waitFor()
await shot(page, 't1-new-conversation')

await composer.fill(question)
await page.keyboard.press('Enter')
const firstCite = page.getByRole('button', { name: /^Citation 1, lines? / }).first()
await firstCite.waitFor({ timeout: 120_000 })
await page.waitForFunction(() => !document.querySelector('[aria-busy=true]'), null, { timeout: 120_000 })
await firstCite.click()

if (markdown) {
  const mdPin = page.locator('.ad-md-pin').first()
  await mdPin.waitFor({ timeout: 10_000 })
  await page.waitForTimeout(400)
  if ((await mdPin.textContent()) !== '1') throw new Error('preview pin label should be 1')
  if (!(await page.locator('.ad-md-hit').count())) throw new Error('no cited block washed in preview')
  if (!(await inView(page.locator('.ad-md-hit').first()))) throw new Error('cited block not scrolled into view in preview')
  await shot(page, 't2a-preview-cited')
  await page.getByRole('radio', { name: 'Markdown' }).click()
  await page.locator('.ad-sheet .ad-tl').first().waitFor()
  await firstCite.click()
}

const pin = page.locator('.ad-tl .ad-pin').first()
await pin.waitFor({ timeout: 10_000 })
await page.waitForTimeout(400)
const label = await firstCite.getAttribute('aria-label') // "Citation 1, lines 296–312"
const [, a, b] = label.replace(/,/g, '').match(/lines? (\d+)(?:–(\d+))?/)
const [from, to] = [Number(a), Number(b ?? a)]
const pinLine = Number(await pin.evaluate((el) => el.closest('.ad-tl').getAttribute('data-line')))
if (pinLine !== from) throw new Error(`pin on line ${pinLine}, citation starts at line ${from}`)
if ((await pin.textContent()) !== '1') throw new Error('pin label should match citation number 1')
const marked = await page.$$eval('mark[data-kinds~="evidence"]', (ms) => ms.map((m) => Number(m.closest('.ad-tl').getAttribute('data-line'))))
if (!marked.length || marked.some((l) => l < from || l > to)) throw new Error(`marks on lines ${marked}, citation is ${from}–${to}`)
if (!(await inView(pin))) throw new Error('evidence is not scrolled into view')
await shot(page, 't2-cited')

await page.getByRole('textbox', { name: 'Find in document' }).fill(process.env.FIND ?? 'the')
await page.keyboard.press('Enter')
await page.locator('mark[data-kinds~="find-current"]').first().waitFor({ timeout: 5_000 })
await shot(page, 't3-find')

await page.getByRole('button', { name: 'Light theme' }).click()
await page.waitForTimeout(300)
await firstCite.click()
await page.waitForTimeout(400)
await shot(page, 't4-light')
await page.getByRole('button', { name: 'Dark theme' }).click()

await page.setViewportSize({ width: 390, height: 844 })
await page.waitForTimeout(600)
await shot(page, 't5-mobile')
console.log(`OK: citation 1 at lines ${from}–${to}; ${marked.length} marked line(s); pin on line ${pinLine}`)
await browser.close()

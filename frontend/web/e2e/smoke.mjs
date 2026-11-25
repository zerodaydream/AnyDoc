// End-to-end smoke of the core flow against a running stack (api + worker + vite).
// Usage: BROWSER=/path/to/chromium node e2e/smoke.mjs [pdf] [outDir]
// Uploads (if a PDF is given), waits for ready, asks a question, clicks the first citation,
// asserts a highlight is painted on the right page, and saves screenshots.
import { chromium } from 'playwright-core'

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
const [pdf, out = '.'] = process.argv.slice(2)
const question = process.env.QUESTION ?? 'Which optimizer was used, and what were beta1 and beta2?'

const browser = await chromium.launch({ executablePath: process.env.BROWSER, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
page.on('pageerror', (e) => console.error('pageerror:', e.message))
await page.goto(BASE)

if (pdf) {
  await page.getByRole('button', { name: 'Open a new document' }).click().catch(() => {})
  await page.locator('input[type=file]').setInputFiles(pdf)
}
await page.getByRole('textbox', { name: 'Ask about this document' }).waitFor()
await page.waitForFunction(() => !document.querySelector('textarea')?.disabled, null, { timeout: 120_000 })
await page.locator('.pdfViewer .page canvas').first().waitFor({ timeout: 30_000 })
await page.screenshot({ path: `${out}/1-ready.png` })

await page.getByRole('textbox', { name: 'Ask about this document' }).fill(question)
await page.keyboard.press('Enter')
const firstCite = page.getByRole('button', { name: /^Citation 1, page/ }).last()
await firstCite.waitFor({ timeout: 90_000 })
await page.waitForFunction(() => !document.querySelector('[aria-busy=true]'), null, { timeout: 90_000 })
await firstCite.click()
const hl = page.locator('.pdfViewer .page[data-page-number] .ad-hl').first()
await hl.waitFor({ timeout: 15_000 })
const label = await firstCite.getAttribute('aria-label')
const want = Number(label.match(/page (\d+)/)[1])
const hlPage = await hl.evaluate((el) => Number(el.closest('.page')?.getAttribute('data-page-number')))
if (hlPage !== want) throw new Error(`highlight on page ${hlPage}, citation says ${want}`)
await page.waitForTimeout(400)
await page.screenshot({ path: `${out}/2-cited.png` })

await page.getByRole('button', { name: /Switch to light theme/ }).click()
await page.waitForTimeout(300)
await page.screenshot({ path: `${out}/3-light.png` })
await page.getByRole('button', { name: /Switch to dark theme/ }).click()

await page.setViewportSize({ width: 390, height: 844 })
await page.locator('.pdfViewer .page canvas').first().waitFor({ timeout: 30_000 })
await page.waitForTimeout(500)
await page.screenshot({ path: `${out}/4-mobile.png` })
console.log(`OK: citation page ${want}, highlight painted on page ${hlPage}`)
await browser.close()

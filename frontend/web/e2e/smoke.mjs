// End-to-end smoke of the core flow against a running stack (api + worker + vite).
// Usage: BROWSER=/path/to/chromium node e2e/smoke.mjs [pdf] [outDir]
// Starts a new conversation (uploading the PDF if given, else on the first ready document), asks a
// question, clicks citation 1, asserts the highlight + margin pin are on the cited page, saves screenshots.
import { chromium } from 'playwright-core'

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
const [pdf, out = '.'] = process.argv.slice(2)
const question = process.env.QUESTION ?? 'Which optimizer was used, and what were beta1 and beta2?'
const shot = (page, name) => page.screenshot({ path: `${out}/${name}.png` })

const browser = await chromium.launch({ executablePath: process.env.BROWSER, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
page.on('pageerror', (e) => console.error('pageerror:', e.message))
await page.goto(`${BASE}/#/`)
await page.getByRole('heading', { level: 1 }).waitFor()
await shot(page, '0-home')

if (pdf) await page.locator('input[type=file]').setInputFiles(pdf)
else await page.getByRole('button', { name: /pages$/ }).first().click()

const composer = page.getByRole('textbox', { name: 'Ask about this document' })
await composer.waitFor()
await page.waitForFunction(() => !document.querySelector('textarea')?.disabled, null, { timeout: 180_000 })
await page.locator('.pdfViewer .page canvas').first().waitFor({ timeout: 30_000 })
await page.getByText('What would you like to know?').waitFor()
await shot(page, '1-new-conversation')

await composer.fill(question)
await page.keyboard.press('Enter')
const firstCite = page.getByRole('button', { name: /^Citation 1, page/ }).first()
await firstCite.waitFor({ timeout: 120_000 })
await page.waitForFunction(() => !document.querySelector('[aria-busy=true]'), null, { timeout: 120_000 })
const thinks = await page.getByText('Thought', { exact: true }).count()
console.log(thinks ? 'thinking block shown' : 'no thinking block (model did not return thoughts)')
await firstCite.click()
await page.locator('.pdfViewer .page[data-page-number] .ad-pin').first().waitFor({ timeout: 15_000 })
await page.waitForTimeout(800) // let pdf.js finish re-rendering the target page (pins are repainted then)
const want = Number((await firstCite.getAttribute('aria-label')).match(/page (\d+)/)[1])
const pin = page.locator('.pdfViewer .page[data-page-number] .ad-pin').first()
const pinPage = await pin.evaluate((el) => Number(el.closest('.page')?.getAttribute('data-page-number')))
const shown = Number(await page.getByRole('textbox', { name: 'Page number' }).inputValue())
if (shown !== want) throw new Error(`toolbar shows page ${shown}, citation says ${want}`)
if (pinPage !== want) throw new Error(`pin on page ${pinPage}, citation says ${want}`)
if ((await pin.textContent()) !== '1') throw new Error('pin label should match citation number 1')
await page.waitForTimeout(400)
await shot(page, '2-cited')

// Conversation title came from the first question and the sidebar lists it.
const title = question.slice(0, 30)
await page.getByRole('navigation', { name: 'Conversations' }).getByText(title, { exact: false }).first().waitFor()

if (thinks) {
  await page.getByText('Thought', { exact: true }).click()
  await page.waitForTimeout(250)
  await shot(page, '2b-thinking-open')
}
await page.getByRole('button', { name: 'Thinking' }).click()
await shot(page, '2c-thinking-menu')
await page.keyboard.press('Escape')
await page.getByRole('button', { name: 'Model' }).click()
await shot(page, '2d-model-menu')
await page.keyboard.press('Escape')

await page.keyboard.press('Control+b')
await page.waitForTimeout(350)
await shot(page, '3-sidebar-collapsed')
await page.keyboard.press('Control+b')

await page.getByRole('button', { name: 'Light theme' }).click()
await page.waitForTimeout(300)
await shot(page, '4-light')
await page.getByRole('button', { name: 'Dark theme' }).click()

await page.setViewportSize({ width: 390, height: 844 })
await page.locator('.pdfViewer .page canvas').first().waitFor({ timeout: 30_000 })
await page.waitForTimeout(600)
await shot(page, '5-mobile')
console.log(`OK: citation 1 on page ${want}; highlight + margin pin on page ${pinPage}`)
await browser.close()

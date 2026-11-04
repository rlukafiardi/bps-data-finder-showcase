// Opens catalog links in Chrome and checks that each page shows its table or document title.
//   node tests/e2e/links.mjs sample.json      sample: [{name, url, title}]
// Visits bps.go.id sites: one page per 15 s, because the sites answer 429 to faster visitors.
import { readFileSync } from "node:fs";
import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
if (!process.argv[2]) throw new Error("usage: node tests/e2e/links.mjs sample.json");
const sample = JSON.parse(readFileSync(process.argv[2], "utf8"));
const norm = (t) => t.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
let bad = 0;
for (const item of sample) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1100, height: 900 });
  const failed = [];
  page.on("response", (r) => { if (r.status() >= 400 && !/\.(png|jpe?g|svg|ico|woff2?)(\?|$)/.test(r.url())) failed.push(`${r.status()} ${r.url().slice(0, 90)}`); });
  try {
    const response = await page.goto(item.url, { waitUntil: "domcontentloaded", timeout: 40000 });
    await new Promise((r) => setTimeout(r, 9000)); // the table pages draw themselves after load
    await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Tutup")?.click()); // service notice
    await new Promise((r) => setTimeout(r, 4000));
    const body = norm(await page.evaluate(() => document.body.innerText));
    const found = body.includes(norm(item.title).slice(0, 35));
    if (!found) bad++;
    console.log(`${found ? "ok  " : "FAIL"} ${item.name} HTTP ${response.status()} text ${body.length} chars: ${body.slice(0, 110)}`);
    if (failed.length) console.log(`     failed requests: ${failed.slice(0, 3).join(" | ")}`);
    await page.screenshot({ path: `tests/e2e/shots/link-${item.name.replace(/\W+/g, "-")}.png` });
  } catch (e) {
    bad++;
    console.log(`FAIL ${item.name} ${e.message.slice(0, 80)}`);
  }
  await page.close();
  await new Promise((r) => setTimeout(r, 15000));
}
await browser.close();
console.log(bad ? `\n${bad} of ${sample.length} did not show their title` : "\nall links show their title");
process.exit(bad ? 1 : 0);

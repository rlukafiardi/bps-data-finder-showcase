// Browser check of the deployed page against the live API: search, open a table, no CSP violation or page error,
// no request to a third party, no sideways scroll on a phone. Real data, so it checks shape, not exact numbers.
//   node tests/e2e/live.mjs [https://cari-data-bps.netlify.app]
import assert from "node:assert/strict";
import puppeteer from "puppeteer-core";

const SITE = process.argv[2] ?? "https://cari-data-bps.netlify.app";
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
let failed = 0;

for (const [label, width, height] of [["desktop", 1280, 800], ["phone", 390, 844]]) {
  const page = await browser.newPage();
  await page.setViewport({ width, height, isMobile: width < 600, hasTouch: width < 600 });
  const hosts = new Set(), errors = [];
  page.on("request", (r) => hosts.add(new URL(r.url()).origin));
  page.on("pageerror", (e) => errors.push(e.message));
  await page.evaluateOnNewDocument(() => document.addEventListener("securitypolicyviolation", (e) => (window.__csp = (window.__csp ?? []).concat(e.violatedDirective))));
  try {
    await page.goto(SITE, { waitUntil: "networkidle2" });
    const api = await page.evaluate(() => window.API_BASE);
    if (await page.$eval("#welcome", (n) => !n.hidden)) await page.click("#welcome-start");
    await page.type("#q", "jumlah penduduk miskin kabupaten garut");
    await page.keyboard.press("Enter");
    await page.waitForSelector("#results .result", { timeout: 90000 });
    assert.equal((await page.$$("#results .result")).length, 5, "five results");
    await page.click("#results .result button.primary");
    await page.waitForFunction(() => !document.getElementById("table-wrap").hidden || document.getElementById("panel-status").classList.contains("error"), { timeout: 90000 });
    assert.equal(await page.$eval("#panel-status", (n) => n.classList.contains("error")), false, await page.$eval("#panel-status", (n) => n.textContent));
    const cells = await page.$$eval("#table-wrap td", (n) => n.filter((x) => x.textContent.trim() && x.textContent !== "–").length);
    assert.ok(cells > 0, "the table shows numbers");
    await page.screenshot({ path: `tests/e2e/shots/live-${label}.png` });
    assert.deepEqual((await page.evaluate(() => window.__csp)) ?? [], [], "CSP violations");
    assert.deepEqual(errors, [], "page errors");
    const third = [...hosts].filter((h) => h !== new URL(SITE).origin && h !== api && !h.startsWith("data:"));
    assert.deepEqual(third, [], "requests to third parties");
    if (width < 600) assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no sideways scroll");
    console.log(`  ok   ${label}: 5 results, table with ${cells} numbers, no CSP violation, no third-party request`);
  } catch (e) {
    failed++;
    const status = await page.$eval("#status", (n) => n.textContent).catch(() => "");
    console.log(`  FAIL ${label}: ${e.message.split("\n")[0]} (page says: ${status})`);
  }
}
await browser.close();
process.exit(failed ? 1 : 0);

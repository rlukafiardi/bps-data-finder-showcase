// Browser test of the page in real Chrome. Default: the page against a fake API that replays recorded
// responses and counts calls. LIVE=1: the page against the real API on :8000 (calls Gemini and BPS).
//   npm run test:e2e        LIVE=1 npm run test:e2e
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import puppeteer from "puppeteer-core";
import { fakeApi } from "./fake_api.mjs";
import { serveWeb } from "./serve.mjs";

const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const LIVE = Boolean(process.env.LIVE);
const WEB = "http://localhost:8080";
const API = LIVE ? "http://localhost:8000" : "http://localhost:8001";
const SHOTS = "tests/e2e/shots";
const QUESTION = "jumlah penduduk miskin kabupaten garut";
const BANNED = /\b(anda|saya|kami|kita|aku|kamu|\w{3,}mu|silakan|mohon|terlebih dahulu|diminta oleh|dapat|median|interval|persentil|percentile|variance|varians|model)\b/i;
const fixture = (name) => JSON.parse(readFileSync(`tests/e2e/fixtures/${name}`, "utf8"));

mkdirSync(SHOTS, { recursive: true });
const web = await serveWeb(8080, API);
const fake = LIVE ? null : await fakeApi(8001);
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
const failures = [];

async function step(name, body) {
  try {
    await body();
    console.log(`  ok   ${name}`);
  } catch (e) {
    failures.push(name);
    console.log(`  FAIL ${name}\n       ${String(e.message).split("\n").join("\n       ")}`);
  }
}

async function open({ width = 1280, height = 800, blockStorage = false, scheme = null, url = WEB } = {}) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  const phone = width < 600;
  await page.setViewport({ width, height, isMobile: phone, hasTouch: phone });
  const seen = { requests: [], pageErrors: [] };
  page.on("request", (r) => seen.requests.push(r.url()));
  page.on("pageerror", (e) => seen.pageErrors.push(e.message));
  await page.evaluateOnNewDocument((blocked) => {
    document.addEventListener("securitypolicyviolation", (e) => (window.__csp = (window.__csp ?? []).concat(e.violatedDirective)));
    if (blocked) Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
  }, blockStorage);
  if (scheme) await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }]);
  const response = await page.goto(url);
  return { page, seen, response };
}

const hidden = (page, selector) => page.$eval(selector, (n) => n.hidden);
const text = (page, selector) => page.$eval(selector, (n) => n.textContent.trim());
const search = async (page, q) => {
  await page.$eval("#q", (n) => (n.value = ""));
  await page.type("#q", q);
  await page.keyboard.press("Enter");
};
const resultsReady = (page) => page.waitForSelector("#results .result");
const valueReady = (page) => page.waitForFunction(() => !document.getElementById("table-wrap").hidden);
const uiText = (page) =>  // the page's own words; BPS titles, notes and table cells are data
  page.evaluate(() => {
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll(".result h3, #table-wrap, .answer-row, #panel-title, #panel-note, #panel-source, script").forEach((n) => n.remove());
    return clone.textContent.replace(/\s+/g, " ");
  });
const noHorizontalScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const noBanned = async (page) => assert.doesNotMatch(await uiText(page), BANNED);

if (LIVE) {
  console.log("live: real API on :8000");
  await step("search and open a table", async () => {
    const { page } = await open({ url: `${WEB}/?q=${encodeURIComponent("TPT kota bandung 2025")}` });
    await resultsReady(page);
    console.log("       regions:", await text(page, "#regions"));
    await page.click("#results .result button.primary");
    await valueReady(page);
    const rows = await page.$$eval("#table-wrap tbody tr", (r) => r.length);
    assert.ok(rows >= 2, `rows: ${rows}`);
    await page.screenshot({ path: `${SHOTS}/live-panel.png` });
  });
} else {
  console.log("fake API on :8001");

  await step("first visit: welcome card, remembered, reopened by ?", async () => {
    const { page } = await open();
    assert.equal(await hidden(page, "#welcome"), false);
    assert.equal(await text(page, "#title"), "Mau cari data BPS apa?");
    assert.equal(await text(page, "#welcome-title"), "Cara pakai");
    // only tables show numbers: publications and press releases are links, so no page text may promise numbers for them
    const promise = await page.evaluate(() => [document.querySelector(".lead").textContent, document.querySelector("meta[name=description]").content, document.getElementById("welcome").textContent].join(" "));
    assert.doesNotMatch(promise, /lengkap dengan angka/i);
    assert.match(await text(page, ".lead"), /Angka tabel langsung tampil/);
    assert.match(await text(page, "#welcome"), /Untuk tabel, tekan Lihat Angkanya\. Publikasi dan berita resmi dibuka di BPS/);
    const order = await page.evaluate(() => document.getElementById("search").compareDocumentPosition(document.getElementById("welcome")));
    assert.ok(order & 4, "the search box comes before the how-to card");
    await page.click("#welcome-start");
    assert.equal(await hidden(page, "#welcome"), true);
    assert.equal(await page.evaluate(() => document.activeElement.id), "q");
    await page.reload();
    assert.equal(await hidden(page, "#welcome"), true);
    await page.click("#help");
    assert.equal(await hidden(page, "#welcome"), false);
    assert.equal(await page.$eval("#help", (n) => n.getAttribute("aria-expanded")), "true");
  });

  await step("main flow: Enter searches, region echoed, numbers shown exactly as recorded, period, Esc returns focus", async () => {
    const { page, seen, response } = await open();
    await page.click("#welcome-start");
    await search(page, QUESTION);
    await resultsReady(page);
    assert.equal(fake.calls.search.at(-1), QUESTION, "Enter must send the latest typed text");
    assert.equal((await page.$$("#results .result")).length, 5);
    assert.match(await text(page, "#regions"), /Daerah yang dikenali: Kabupaten Garut/);
    await noBanned(page);

    await page.click("#results .result:nth-child(2) button.primary");
    await valueReady(page);
    const sent = fake.calls.value.at(-1);
    assert.ok(sent.doc_id.startsWith("simdasi:") && sent.regions === "3205", JSON.stringify(sent));
    const recorded = fixture("value_simdasi.json").rows.find((r) => r.highlight);
    const shown = await page.$$eval("#table-wrap tr.hit > *", (cells) => cells.map((c) => c.textContent));
    assert.deepEqual(shown, [recorded.label, ...recorded.values.map((v) => v ?? "–")]);
    assert.equal(await hidden(page, "#legend"), false);
    const columns = fixture("value_simdasi.json").columns;
    const last3 = recorded.values.map((v, i) => [columns[i], v]).filter(([, v]) => v !== null).slice(-3);
    const answer = await page.$$eval("#answer .answer-row", (rows) => rows.map((r) => ({
      label: r.querySelector("h3").textContent,
      pairs: [...r.querySelectorAll("dl > div")].map((d) => [d.querySelector("dt").textContent, d.querySelector("dd").textContent]),
    })));
    assert.deepEqual(answer, [{ label: recorded.label, pairs: last3 }], "answer strip must copy the recorded cells");
    assert.match(await text(page, "#answer"), /Tiga kolom terakhir/);
    assert.match(await text(page, "#panel-fetched"), /Angka diambil dari BPS pada .+ WIB\./);
    assert.ok((await page.$$("#period option")).length >= 2);
    await noBanned(page);

    const before = fake.calls.value.length;
    await page.select("#period", "2024");
    while (fake.calls.value.length === before) await new Promise((r) => setTimeout(r, 50));
    assert.equal(fake.calls.value.at(-1).period, "2024");
    await page.waitForFunction(() => document.getElementById("period").value === "2024");

    await page.keyboard.press("Escape");
    assert.equal(await hidden(page, "#panel"), true);
    assert.equal(await page.evaluate(() => document.activeElement.closest(".result") === document.querySelector(".result:nth-child(2)")), true);

    assert.equal(await page.evaluate(() => window.__csp), undefined, "CSP violation");
    const csp = response.headers()["content-security-policy"];
    assert.match(csp, /frame-ancestors 'none'/);
    assert.match(csp, /connect-src 'self' http:\/\/localhost:8001/);
    assert.equal(response.headers()["x-content-type-options"], "nosniff");
    const outside = seen.requests.filter((u) => !u.startsWith(WEB) && !u.startsWith(API) && !u.startsWith("data:"));
    assert.deepEqual(outside, [], "third-party requests");
    assert.deepEqual(seen.pageErrors, []);
  });

  await step("old tables are tagged, the best match is marked, the year comes from the title", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, QUESTION);
    await resultsReady(page);
    const tags = await page.$$eval("#results .result", (cards) => cards.map((c) => ({
      tags: [...c.querySelectorAll(".tag")].map((t) => t.textContent),
      facts: c.querySelector(".small")?.textContent ?? "",
    })));
    assert.deepEqual(tags[0].tags, ["Data lama"], "2002-2016 archive table");
    assert.match(tags[0].facts, /Tahun terakhir di judul: 2016/);
    assert.deepEqual(tags[1].tags, [], "Dalam Angka 2017-2025 is current");
    assert.match(tags[1].facts, /Tahun tersedia: 2017-2025/);
    assert.equal(tags.flatMap((t) => t.tags).filter((t) => t === "Paling cocok").length, 0, "an old table is not called the best match");
    await search(page, "inflasi indonesia oktober 2026");
    await page.waitForFunction(() => document.querySelector("#results .result .badge")?.textContent === "Berita Resmi");
    assert.deepEqual(await page.$$eval("#results .result:first-child .tag", (n) => n.map((t) => t.textContent)), ["Paling cocok"]);
    assert.equal(await page.$$eval("#results .tag.best", (n) => n.length), 1, "only the first result");
    await noBanned(page);
  });

  await step("dynamic and archive tables highlight the asked region", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, QUESTION);
    await resultsReady(page);
    await page.click("#results .result:nth-child(3) button.primary");  // Tabel angka
    await valueReady(page);
    assert.equal(await text(page, "#table-wrap tr.hit th"), "Kota Bandung");
    await page.click("#panel-close");
    await page.click("#results .result:nth-child(1) button.primary");  // Tabel arsip
    await valueReady(page);
    assert.equal(await text(page, "#table-wrap tr.hit th"), "5. Garut");
    const archive = fixture("value_static.json");  // 15 columns: the strip must show the newest three, not the first
    const garut = archive.rows.find((r) => r.highlight);
    const expected = garut.values.map((v, i) => [archive.columns[i], v]).filter(([, v]) => v !== null).slice(-3);
    assert.deepEqual(
      await page.$$eval("#answer dl > div", (d) => d.map((x) => [x.querySelector("dt").textContent, x.querySelector("dd").textContent])),
      expected,
    );
  });

  await step("press releases are links only", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, "inflasi indonesia oktober 2026");
    await resultsReady(page);
    const first = await page.$eval("#results .result", (n) => ({
      buttons: [...n.querySelectorAll(".actions button")].map((b) => b.textContent),
      link: [...n.querySelectorAll("a")].map((a) => [a.textContent, a.target, a.rel, a.href.slice(0, 8)]),
    }));
    assert.deepEqual(first.buttons, ["Salin Kutipan"]);
    const item = fixture("search_brs.json").results[0];
    await page.browserContext().overridePermissions(WEB, ["clipboard-read", "clipboard-write", "clipboard-sanitized-write"]);
    await page.click("#results .result .actions button");
    await page.waitForFunction(() => /Tersalin/.test(document.querySelector("#results .result .actions button").textContent));
    const today = new Date().toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Jakarta" });
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), `"${item.title}", Badan Pusat Statistik, diakses ${today} dari ${item.url}`);
    assert.deepEqual(first.link, [["Buka di BPS", "_blank", "noopener noreferrer", "https://"]]);
    assert.match(await text(page, "#regions"), /Indonesia/);
  });

  await step("a question without a region says national data was searched", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, "tanpa daerah");
    await resultsReady(page);
    assert.equal(await text(page, "#regions"), "Pertanyaan tidak menyebut daerah, jadi yang dicari data nasional.");
    await noBanned(page);
  });

  await step("a slow search says the server is waking up; a fast one never does", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, "tanpa daerah");
    await resultsReady(page);
    await new Promise((r) => setTimeout(r, 5500)); // past the slow timer: a timer left running would overwrite the count
    assert.match(await text(page, "#status"), /^5 hasil paling cocok$/);

    await page.$eval("#results", (n) => n.replaceChildren());
    await search(page, "lambat");
    await page.waitForFunction(() => /satu menit/.test(document.getElementById("status").textContent), { timeout: 5800 });
    assert.match(await text(page, "#status"), /baru bangun/);
    await page.waitForFunction(() => /hasil paling cocok/.test(document.getElementById("status").textContent));
    assert.doesNotMatch(await text(page, "#status"), /bangun/);
    await noBanned(page);
  });

  await step("feedback: Ya and Tidak send the question and result once, a refusal can be retried", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, QUESTION);
    await resultsReady(page);
    const ids = fixture("search.json").results.map((r) => r.doc_id);
    const before = fake.calls.feedback.length;
    await page.click("#results .result:nth-child(1) .feedback button:first-of-type");
    await page.waitForFunction(() => /tercatat/.test(document.querySelector("#results .result .feedback").textContent));
    assert.deepEqual(fake.calls.feedback.slice(before), [{ q: QUESTION, doc_id: ids[0], verdict: "ya" }]);
    assert.equal((await page.$$("#results .result:nth-child(1) .feedback button")).length, 0, "no second vote on the same result");
    await page.click("#results .result:nth-child(2) .feedback button:last-of-type");
    await page.waitForFunction((n) => document.querySelectorAll("#results .result")[1].querySelector(".feedback").textContent.includes("tercatat"), {}, 0);
    assert.equal(fake.calls.feedback.at(-1).verdict, "tidak");

    await search(page, "antre"); // result 2 of this search makes the fake API refuse feedback
    await resultsReady(page);
    await page.click("#results .result:nth-child(2) .feedback button:first-of-type");
    await page.waitForFunction(() => /Belum terkirim/.test(document.querySelectorAll("#results .result")[1].querySelector(".feedback").textContent));
    assert.equal(await page.$$eval("#results .result:nth-child(2) .feedback button", (b) => b.filter((x) => !x.disabled).length), 2, "buttons come back");
    await noBanned(page);
  });

  await step("table tools: citation with today's date, CSV exactly as shown, shared link reopens the table", async () => {
    const value = fixture("value_var.json"); // the third result of the recorded search is this var table
    const docId = fixture("search.json").results[2].doc_id;
    const { page } = await open();
    const context = page.browserContext();
    await context.overridePermissions(WEB, ["clipboard-read", "clipboard-write", "clipboard-sanitized-write"]);
    const downloads = mkdtempSync(join(tmpdir(), "csv-"));
    await (await browser.target().createCDPSession()).send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: downloads, browserContextId: context.id });
    const clipboard = () => page.evaluate(() => navigator.clipboard.readText());
    const fileAfterClick = async (selector) => {
      const before = readdirSync(downloads).length;
      await page.click(selector);
      while (readdirSync(downloads).filter((f) => !f.endsWith(".crdownload")).length === before) await new Promise((r) => setTimeout(r, 50));
      const name = readdirSync(downloads).filter((f) => !f.endsWith(".crdownload")).sort().at(-1);
      return { name, text: readFileSync(join(downloads, name), "utf8") };
    };
    await page.click("#welcome-start");
    await search(page, QUESTION);
    await resultsReady(page);
    await page.click("#results .result:nth-child(3) button.primary");
    await valueReady(page);

    await page.bringToFront();
    await page.click("#panel-cite");
    await page.waitForFunction(() => document.getElementById("panel-cite").textContent !== "Salin Kutipan");
    assert.equal(await text(page, "#panel-cite"), "Tersalin");
    const today = new Date().toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Jakarta" });
    assert.equal(await clipboard(), `"${value.title}", Badan Pusat Statistik, diakses ${today} dari ${value.url}`);
    await page.waitForFunction(() => document.getElementById("panel-cite").textContent === "Salin Kutipan");

    const csv = await fileAfterClick("#panel-csv");
    assert.equal(csv.name, "bps-tingkat-pengangguran-terbuka-kabupaten-kota.csv");
    const expected = [["Keterangan", ...value.columns], ...value.rows.map((r) => [r.label, ...r.values])];
    assert.equal(csv.text, "\uFEFF" + expected.map((cells) => cells.join(";")).join("\r\n"));

    await page.click("#panel-share");
    await page.waitForFunction(() => document.getElementById("panel-share").textContent === "Tersalin");
    const link = new URL(await clipboard());
    assert.equal(link.origin + link.pathname, WEB + "/");
    assert.equal(link.searchParams.get("q"), QUESTION);
    assert.equal(link.searchParams.get("buka"), docId);

    const opened = await open({ url: link.href });
    await valueReady(opened.page);
    assert.equal(fake.calls.value.at(-1).doc_id, docId);
    assert.ok(fake.calls.value.at(-1).regions, "the asked region is known before the table loads");
    assert.equal(await text(opened.page, "#panel-title"), value.title);
    assert.ok((await opened.page.$$("#results .result")).length > 0, "the results behind the panel are shown");
    const searches = fake.calls.search.length;
    const bare = await open({ url: `${WEB}/?buka=${encodeURIComponent(docId)}` });
    await valueReady(bare.page);
    assert.equal(fake.calls.search.length, searches, "a link without a question does not search");
    await noBanned(page);
  });

  await step("CSV never carries a formula: only cells that start like one get a quote in front", async () => {
    const { page } = await open();
    const downloads = mkdtempSync(join(tmpdir(), "csv-"));
    await (await browser.target().createCDPSession()).send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: downloads, browserContextId: page.browserContext().id });
    await page.click("#welcome-start");
    await search(page, "rumus");
    await resultsReady(page);
    await page.click("#results .result:nth-child(3) button.primary");
    await valueReady(page);
    await page.click("#panel-csv");
    while (!readdirSync(downloads).some((f) => f.endsWith(".csv"))) await new Promise((r) => setTimeout(r, 50));
    const rows = readFileSync(join(downloads, readdirSync(downloads).find((f) => f.endsWith(".csv"))), "utf8").split("\r\n");
    assert.equal(rows[1].split(";")[0], `"'=HYPERLINK(""http://evil.example"")"`);
    assert.equal(rows[2], fixture("value_var.json").rows[1].label + ";" + fixture("value_var.json").rows[1].values[0], "other rows stay as given");
  });

  await step("Dalam Angka results have no BPS link while BPS's pages fail; other tables keep theirs", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, QUESTION);
    await resultsReady(page);
    const kinds = fixture("search.json").results.map((r) => r.type);
    const cards = await page.$$eval("#results .result", (n) => n.map((c) => ({ links: c.querySelectorAll(".actions a").length, note: /sedang bermasalah/.test(c.textContent) })));
    kinds.forEach((kind, i) => assert.deepEqual(cards[i], kind === "simdasi" ? { links: 0, note: true } : { links: 1, note: false }, `card ${i + 1} (${kind})`));
    const openCard = async (nth) => {
      await page.click(`#results .result:nth-child(${nth}) button.primary`);
      await valueReady(page);
      return { link: !(await hidden(page, "#panel-link")), note: !(await hidden(page, "#panel-down")) };
    };
    assert.deepEqual(await openCard(kinds.indexOf("simdasi") + 1), { link: false, note: true });
    await page.click("#panel-close");
    assert.deepEqual(await openCard(kinds.indexOf("var") + 1), { link: true, note: false });
    await noBanned(page);
  });

  await step("a result without a BPS link shows the numbers but no link", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, "tanpa tautan");
    await resultsReady(page);
    assert.equal((await page.$$("#results .result a")).length, 0);
    assert.equal((await page.$$("#results .result button.primary")).length, 5);
    await page.click("#results .result:nth-child(2) button.primary");
    await valueReady(page);
    assert.equal(await hidden(page, "#panel-link"), true);
  });

  await step("refusals: empty, one letter, nothing found, limit, server down, BPS busy", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    const calls = fake.calls.search.length;
    await page.click("#go");
    assert.match(await text(page, "#q-error"), /Tulis dulu pertanyaannya/);
    await search(page, "a");
    assert.match(await text(page, "#q-error"), /minimal dua huruf/);
    assert.equal(fake.calls.search.length, calls, "no request for invalid input");

    await search(page, "kosong");
    await page.waitForFunction(() => /Belum ketemu/.test(document.getElementById("status").textContent));
    assert.equal((await page.$$("#results .result")).length, 0);
    await search(page, "nihil");
    await page.waitForFunction(() => /belum punya data yang pas/.test(document.getElementById("status").textContent));
    assert.equal((await page.$$("#results .result")).length, 0, "no cards until asked");
    await page.click("#results button");
    await page.waitForFunction(() => document.querySelectorAll("#results .result").length > 0);
    assert.match(await text(page, "#status"), /hasil terdekat, mungkin kurang cocok/);
    await search(page, "limit");
    await page.waitForFunction(() => /Terlalu banyak pencarian/.test(document.getElementById("status").textContent));
    assert.ok(await page.$eval("#status", (n) => n.classList.contains("error")));
    await search(page, "putus");
    await page.waitForFunction(() => /Tidak bisa terhubung ke server/.test(document.getElementById("status").textContent));
    assert.equal(await page.$eval("#go", (n) => n.disabled), false, "search button must come back");

    await search(page, "antre");
    await resultsReady(page);
    await page.click("#results .result:nth-child(2) button.primary");
    await page.waitForFunction(() => /Sedang ramai/.test(document.getElementById("panel-status").textContent));
    assert.equal(await hidden(page, "#table-wrap"), true);
    await noBanned(page);
  });

  await step("hostile text from the API is shown as text, never run", async () => {
    const { page } = await open();
    await page.click("#welcome-start");
    await search(page, "xss");
    await resultsReady(page);
    assert.match(await text(page, "#results .result h3"), /<img src=x onerror=/);
    assert.equal((await page.$$("#results img")).length, 0);
    await page.click("#results .result:nth-child(2) button.primary");
    await valueReady(page);
    assert.equal((await page.$$("#table-wrap img")).length, 0);
    assert.equal(await page.evaluate(() => window.__xss), undefined);
  });

  await step("shared link opens the results; blocked storage does not break the page", async () => {
    const { page, seen } = await open({ blockStorage: true, url: `${WEB}/?q=${encodeURIComponent(QUESTION)}` });
    await resultsReady(page);
    assert.equal(await hidden(page, "#welcome"), true);
    assert.equal(await page.$eval("#q", (n) => n.value), QUESTION);
    const plain = await open({ blockStorage: true });
    assert.equal(await hidden(plain.page, "#welcome"), false, "welcome shows when it cannot be remembered");
    assert.deepEqual([...seen.pageErrors, ...plain.seen.pageErrors], []);
  });

  async function layout(label, viewport) {
    const { page } = await open(viewport);
    await page.screenshot({ path: `${SHOTS}/${label}-1-welcome.png` });
    assert.ok(await noHorizontalScroll(page), "welcome scrolls sideways");
    await page.click("#welcome-start");
    await search(page, QUESTION);
    await resultsReady(page);
    await page.screenshot({ path: `${SHOTS}/${label}-2-results.png` });
    assert.ok(await noHorizontalScroll(page), "results scroll sideways");
    const small = await page.$$eval("button.primary, button.secondary, button.icon, .linkbtn, #q", (n) =>
      n.filter((x) => x.offsetParent && x.getBoundingClientRect().height < 44).map((x) => x.textContent || x.id));
    assert.deepEqual(small, [], "targets under 44px");

    await page.click("#results .result:nth-child(1) button.primary");  // the 15-column archive table
    await valueReady(page);
    await page.screenshot({ path: `${SHOTS}/${label}-3-panel.png` });
    assert.ok(await noHorizontalScroll(page), "panel scrolls the page sideways");
    const geometry = await page.evaluate(() => {
      const r = document.getElementById("panel").getBoundingClientRect();
      const wrap = document.getElementById("table-wrap");
      const atNewest = wrap.scrollLeft + wrap.clientWidth >= wrap.scrollWidth - 2;
      const before = document.querySelector("#table-wrap tbody th").getBoundingClientRect().left - wrap.getBoundingClientRect().left;
      wrap.scrollLeft = 300;
      const after = document.querySelector("#table-wrap tbody th").getBoundingClientRect().left - wrap.getBoundingClientRect().left;
      return { left: r.left, right: r.right, bottom: r.bottom, top: r.top, width: r.width, vw: innerWidth, vh: innerHeight,
               scrolls: wrap.scrollWidth > wrap.clientWidth, stickyDrift: Math.abs(after - before), atNewest,
               modal: document.getElementById("panel").getAttribute("aria-modal"),
               backdrop: getComputedStyle(document.getElementById("backdrop")).display,
               listRight: document.getElementById("results").getBoundingClientRect().right };
    });
    const smallTools = await page.$$eval("#panel-tools button, #panel-link", (n) => n.filter((x) => x.offsetParent && x.getBoundingClientRect().height < 44).map((x) => x.textContent));
    assert.deepEqual(smallTools, [], "panel buttons under 44px");
    assert.ok(geometry.scrolls, "wide table must scroll inside its box");
    assert.ok(geometry.stickyDrift < 2, "first column must stay in view");
    assert.ok(geometry.atNewest, "a table with years across opens on the newest year");
    return { ...geometry, page };
  }

  await step("phone 390x844: bottom sheet, no sideways scroll, big targets, sticky first column", async () => {
    const g = await layout("phone", { width: 390, height: 844 });
    assert.ok(g.left === 0 && g.right === g.vw && g.bottom === g.vh, JSON.stringify(g.vw));
    assert.ok(g.top >= g.vh * 0.1, "sheet must leave the page visible above it");
    assert.equal(g.modal, "true");
    assert.notEqual(g.backdrop, "none");
  });

  await step("phone in light mode: same layout", async () => {
    const g = await layout("phone-light", { width: 390, height: 844, scheme: "light" });
    assert.ok(g.left === 0 && g.right === g.vw && g.bottom === g.vh, JSON.stringify(g));
  });

  await step("desktop 1280x800: side panel on the right", async () => {
    const g = await layout("desktop", { width: 1280, height: 800 });
    assert.ok(g.right === g.vw && g.width <= 620 && g.top === 0 && g.bottom === g.vh, JSON.stringify(g.vw));
    assert.equal(g.modal, "false");
    assert.equal(g.backdrop, "none", "no dimming layer beside the list");
    assert.ok(g.listRight <= g.left, `list ${g.listRight} runs under the panel at ${g.left}`);
    await g.page.click("#results .result:nth-child(3) button.primary");  // another table while the panel is open
    await g.page.waitForFunction(() => /Bandung/.test(document.querySelector("#table-wrap tr.hit th")?.textContent ?? ""));
  });
}

await browser.close();
web.close();
fake?.server.close();
console.log(failures.length ? `\n${failures.length} failed: ${failures.join("; ")}` : "\nall passed");
process.exit(failures.length ? 1 : 0);

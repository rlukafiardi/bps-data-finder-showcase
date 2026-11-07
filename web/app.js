"use strict";

const API = window.API_BASE;
const $ = (id) => document.getElementById(id);
const TIMEOUT_MS = 90000; // a sleeping server took 53 s to start on Cloud Run (2026-11-04), and a value can then wait 15 s for a BPS slot

const SLOW_AFTER_MS = 5000; // a server that slept takes about a minute to start: say so instead of a bare "Mencari..."
// bps.go.id's Dalam Angka table pages show "Gagal Memuat Tabel" (2026-11-04), also for links BPS itself supplied: no
// "Buka di BPS" for them until the pages work again (recheck in a browser, then empty this set)
const BPS_PAGE_DOWN = new Set(["simdasi"]);
const BPS_PAGE_DOWN_NOTE = "Halaman BPS untuk tabel ini sedang bermasalah. Angkanya tetap tampil di sini.";
const OLD_AFTER_YEARS = 2; // a table whose newest year is older than this many years ago gets a "Data lama" tag
const YEAR = /(?:19|20)\d{2}/;
const CSV_SEPARATOR = ";"; // Excel with an Indonesian locale splits on ";" because "," is its decimal mark
const WIDE = matchMedia("(min-width: 900px)"); // panel sits beside the results instead of over them

const state = { question: "", regions: [], opener: null, doc: null, data: null };

function remembered(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch {
    return null; // private window or blocked storage: the page works, it just forgets
  }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
  if (!m) return null;
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("id-ID", {
    day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}

async function api(path, params) {
  const url = new URL(path, API);
  for (const [key, value] of Object.entries(params)) if (value) url.searchParams.set(key, value);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response;
  try {
    response = await fetch(url, { signal: controller.signal });
  } catch (e) {
    throw new Error(e.name === "AbortError"
      ? "Server lama menjawab. Coba lagi sebentar."
      : "Tidak bisa terhubung ke server. Cek koneksi internet, lalu coba lagi.");
  } finally {
    clearTimeout(timer);
  }
  if (response.ok) return response.json();
  let detail = null;
  try { detail = (await response.json()).detail; } catch { /* body is not JSON */ }
  throw new Error(typeof detail === "string" ? detail : "Pertanyaannya terlalu pendek atau terlalu panjang.");
}

/* search */

function showWelcome(visible) {
  $("welcome").hidden = !visible;
  $("help").setAttribute("aria-expanded", String(visible));
  if (!visible) remembered("welcome-seen", "1");
}

function setStatus(node, text, isError) {
  node.textContent = text;
  node.classList.toggle("error", Boolean(isError));
}

async function search(question) {
  const q = question.trim();
  const error = $("q-error");
  if (q.length < 2) {
    error.textContent = "Tulis dulu pertanyaannya, minimal dua huruf.";
    $("q").focus();
    return;
  }
  error.textContent = "";
  showWelcome(false);
  $("q").value = q;
  history.replaceState(null, "", "?q=" + encodeURIComponent(q));
  $("go").disabled = true;
  setStatus($("status"), "Mencari...");
  $("results").replaceChildren();
  $("regions").textContent = "";
  const slow = setTimeout(
    () => setStatus($("status"), "Server baru bangun, tunggu sebentar. Bisa sampai satu menit."),
    SLOW_AFTER_MS,
  );
  try {
    renderResults(await api("/api/search", { q }));
  } catch (e) {
    setStatus($("status"), e.message, true);
  } finally {
    clearTimeout(slow);
    $("go").disabled = false;
  }
}

function renderResults(data) {
  state.question = data.question;
  state.regions = data.regions.map((r) => r.id);
  $("examples").hidden = true;
  if (data.results.length === 0) {
    setStatus($("status"), "Belum ketemu. Coba kata yang lebih sederhana, misalnya nama datanya dan daerahnya.");
    return;
  }
  if (data.no_match) {
    // the best result has almost none of the question's words: say so, and keep the nearest tables one tap away
    setStatus($("status"), "Sepertinya BPS belum punya data yang pas untuk ini. Coba kata lain, misalnya nama datanya dan daerahnya.");
    const show = el("button", "", "Lihat hasil terdekat");
    show.type = "button";
    show.addEventListener("click", () => {
      setStatus($("status"), `${data.results.length} hasil terdekat, mungkin kurang cocok`);
      $("results").replaceChildren(...data.results.map(resultCard));
    });
    const item = el("li", "no-match");
    item.append(show);
    $("results").replaceChildren(item);
    return;
  }
  setStatus($("status"), `${data.results.length} hasil paling cocok`);
  $("regions").textContent = data.regions.length
    ? "Daerah yang dikenali: " + data.regions.map((r) => r.name).join(", ")
    : "Pertanyaan tidak menyebut daerah, jadi yang dicari data nasional.";
  $("results").replaceChildren(...data.results.map(resultCard));
}

function resultCard(item, index) {
  const card = el("li", "card result");
  const hasValues = item.type === "var" || item.type === "simdasi" || item.type === "statictable";
  const old = hasValues && item.latest_year && item.latest_year < new Date().getFullYear() - OLD_AFTER_YEARS;
  const meta = el("div", "meta");
  if (index === 0 && !old) meta.append(el("span", "tag best", "Paling cocok"));
  meta.append(el("span", "badge", item.type_label), el("span", "region", item.region));
  if (old) meta.append(el("span", "tag old", "Data lama"));
  const facts = [];
  if (item.years && item.years.length) facts.push(`Tahun tersedia: ${item.years[0]}-${item.years[item.years.length - 1]}`);
  else if (hasValues && item.latest_year) facts.push(`Tahun terakhir di judul: ${item.latest_year}`);
  const date = formatDate(item.date);
  if (date) facts.push((item.type === "publication" || item.type === "pressrelease" ? "Terbit: " : "Diperbarui: ") + date);
  card.append(meta, el("h3", "", item.title));
  if (facts.length) card.append(el("p", "small", facts.join(" · ")));

  const actions = el("div", "actions");
  if (hasValues) {
    const show = el("button", "primary", "Lihat Angkanya");
    show.type = "button";
    show.addEventListener("click", () => openPanel(item, show));
    actions.append(show);
  }
  const pageDown = Boolean(item.url) && BPS_PAGE_DOWN.has(item.type);
  if (item.url && !pageDown) actions.append(bpsLink(item.url, hasValues ? "secondary linkbtn" : "primary linkbtn"));
  if (item.url && !hasValues) { // a table's citation sits in its panel
    const cite = el("button", "secondary", "Salin Kutipan");
    cite.type = "button";
    cite.addEventListener("click", () => copyText(cite, citation(item)));
    actions.append(cite);
  }
  card.append(actions, ...(pageDown ? [el("p", "small", BPS_PAGE_DOWN_NOTE)] : []), feedbackRow(item));
  return card;
}

function feedbackRow(item) {
  const row = el("div", "feedback");
  const buttons = ["Ya", "Tidak"].map((label) => {
    const button = el("button", "secondary", label);
    button.type = "button";
    button.addEventListener("click", () => sendFeedback(item, label.toLowerCase(), row));
    return button;
  });
  row.append(el("span", "small", "Hasil ini cocok?"), ...buttons);
  return row;
}

async function sendFeedback(item, verdict, row) {
  const buttons = row.querySelectorAll("button");
  buttons.forEach((b) => (b.disabled = true));
  try {
    const response = await fetch(new URL("/api/feedback", API), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: state.question, doc_id: item.doc_id, verdict }),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error(String(response.status));
    row.replaceChildren(el("span", "small", "Makasih, masukannya tercatat."));
  } catch {
    buttons.forEach((b) => (b.disabled = false));
    row.querySelector("span").textContent = "Belum terkirim. Coba lagi?";
  }
}

function bpsLink(url, className) {
  const link = el("a", className, "Buka di BPS");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

/* value panel */

function showBpsLink(url, type) {
  const down = Boolean(url) && BPS_PAGE_DOWN.has(type);
  $("panel-link").hidden = !url || down;
  if (url) $("panel-link").href = url;
  $("panel-down").hidden = !down;
  $("panel-down").textContent = down ? BPS_PAGE_DOWN_NOTE : "";
}

function openPanel(item, opener) {
  state.opener = opener;
  state.doc = item;
  $("panel-title").textContent = item.title || "Memuat tabel...";
  showBpsLink(item.url, item.type);
  $("backdrop").hidden = false;
  $("panel").setAttribute("aria-modal", String(!WIDE.matches));
  $("panel").hidden = false;
  document.body.classList.add("panel-open");
  $("panel-close").focus();
  loadValue();
}

function closePanel() {
  $("panel").hidden = true;
  $("backdrop").hidden = true;
  document.body.classList.remove("panel-open");
  (state.opener ?? $("q")).focus();
}

async function loadValue(period) {
  const wrap = $("table-wrap");
  wrap.hidden = true;
  for (const id of ["unit", "panel-note", "panel-source", "panel-fetched"]) $(id).textContent = "";
  $("legend").hidden = true;
  $("answer").hidden = true;
  $("panel-tools").hidden = true;
  state.data = null;
  $("period-box").hidden = true;
  setStatus($("panel-status"), "Mengambil angka dari BPS... Kalau lagi ramai, bisa sampai setengah menit.");
  const doc = state.doc;
  try {
    const data = await api("/api/value", { doc_id: doc.doc_id, period, regions: state.regions.join(",") });
    if (doc !== state.doc) return; // another table was opened while this one loaded
    renderValue(data);
  } catch (e) {
    if (doc === state.doc) setStatus($("panel-status"), e.message, true);
  }
}

// The asked region's row, last three columns with a value: copied as given, never computed. For a table with
// years as columns that is the newest data.
function answerRows(data) {
  return data.rows.filter((r) => r.highlight).slice(0, 2).map((row) => ({
    label: row.label,
    pairs: data.columns.map((c, i) => [c, row.values[i]]).filter(([, v]) => v !== null).slice(-3),
  })).filter((r) => r.pairs.length);
}

function renderAnswer(data) {
  const rows = answerRows(data);
  const nodes = rows.map((r) => {
    const box = el("div", "answer-row");
    const list = el("dl", "answer-values");
    for (const [column, value] of r.pairs) {
      const item = el("div");
      item.append(el("dt", "", column), el("dd", "", value));
      list.append(item);
    }
    box.append(el("h3", "", r.label), list);
    return box;
  });
  if (nodes.length && rows.some((r) => r.pairs.length < data.columns.length)) {
    nodes.push(el("p", "small", "Tiga kolom terakhir di baris ini. Lengkapnya ada di tabel di bawah."));
  }
  $("answer").replaceChildren(...nodes);
  $("answer").hidden = nodes.length === 0;
}

function renderValue(data) {
  state.data = data;
  setStatus($("panel-status"), "");
  if (!state.doc.title) { // opened from a shared link: no search result gave a title or a link
    $("panel-title").textContent = data.title;
    showBpsLink(data.url, data.type);
  }
  $("panel-tools").hidden = false;
  $("panel-cite").hidden = !data.url; // BPS asks for a credit with title, access date and direct link
  if (data.unit) $("unit").textContent = "Satuan: " + data.unit;
  if (data.periods.length > 1) {
    $("period").replaceChildren(...data.periods.map((p) => {
      const option = el("option", "", p.label);
      option.value = p.id;
      option.selected = p.label === data.period;
      return option;
    }));
    $("period-box").hidden = false;
  }
  const table = el("table");
  const head = el("tr");
  head.append(el("th", "", "Keterangan"), ...data.columns.map((c) => el("th", "", c)));
  const thead = el("thead");
  thead.append(head);
  const body = el("tbody");
  for (const row of data.rows) {
    const tr = el("tr", row.highlight ? "hit" : "");
    const label = el("th", "", row.label);
    label.scope = "row";
    tr.append(label, ...row.values.map((v) => (v === null ? el("td", "none", "–") : el("td", "", v))));
    body.append(tr);
  }
  table.append(thead, body);
  const wrap = $("table-wrap");
  wrap.replaceChildren(table);
  wrap.hidden = false;
  renderAnswer(data);
  const years = data.columns.map((c) => (YEAR.exec(c) || [])[0]).filter(Boolean).map(Number);
  if (years.length * 2 >= data.columns.length && years[0] < years.at(-1)) wrap.scrollLeft = wrap.scrollWidth; // oldest year first: open on the newest
  const hit = body.querySelector("tr.hit");
  if (hit) {
    wrap.scrollTop = hit.offsetTop - wrap.clientHeight / 2;
    $("legend").hidden = false;
  }
  $("panel-note").textContent = data.note || "";
  $("panel-source").textContent = data.source ? "Sumber: " + data.source : "";
  const fetched = new Date(data.fetched_at).toLocaleString("id-ID", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta",
  });
  $("panel-fetched").textContent = `Angka diambil dari BPS pada ${fetched} WIB.`;
}

/* citation, CSV and link */

async function copyText(button, text) {
  const label = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Tersalin";
  } catch {
    button.textContent = "Gagal menyalin";
  }
  setTimeout(() => { button.textContent = label; }, 2000);
}

function citation(data) {
  const date = new Date().toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Jakarta" });
  return `"${data.title}", Badan Pusat Statistik, diakses ${date} dari ${data.url}`;
}

function csvCell(value) {
  let text = value ?? "";
  // a spreadsheet runs a cell that starts with = + - @ as a formula; numbers such as "-5,2" and a lone "-" are left as given
  if (/^[=+\-@\t\r]/.test(text) && !/^[+-]?[\d.,]*\d$|^-$/.test(text)) text = "'" + text;
  return text.includes(CSV_SEPARATOR) || /["\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadCsv(data) {
  const lines = [["Keterangan", ...data.columns], ...data.rows.map((r) => [r.label, ...r.values])];
  const csv = "\uFEFF" + lines.map((cells) => cells.map(csvCell).join(CSV_SEPARATOR)).join("\r\n");
  const link = el("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.download = "bps-" + data.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) + ".csv";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function tableLink(data) {
  const params = new URLSearchParams(state.question ? { q: state.question, buka: data.doc_id } : { buka: data.doc_id });
  return `${location.origin}${location.pathname}?${params}`;
}

/* wiring */

$("search").addEventListener("submit", (e) => {
  e.preventDefault();
  search($("q").value);
});
$("q").addEventListener("input", () => { $("q-error").textContent = ""; });
for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => { $("q").value = chip.textContent; search(chip.textContent); });
}
$("help").addEventListener("click", () => showWelcome($("welcome").hidden));
$("welcome-start").addEventListener("click", () => { showWelcome(false); $("q").focus(); });
$("panel-close").addEventListener("click", closePanel);
$("panel-cite").addEventListener("click", (e) => copyText(e.currentTarget, citation(state.data)));
$("panel-share").addEventListener("click", (e) => copyText(e.currentTarget, tableLink(state.data)));
$("panel-csv").addEventListener("click", () => downloadCsv(state.data));
$("backdrop").addEventListener("click", closePanel);
$("period").addEventListener("change", () => loadValue($("period").value));
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("panel").hidden) closePanel(); });

const params = new URLSearchParams(location.search);
const initial = params.get("q");
const linked = params.get("buka"); // a shared link: the search runs first so the asked region is known
const openLinked = () => linked && openPanel({ doc_id: linked, title: "", url: null }, null);
if (initial) {
  $("q").value = initial;
  search(initial).then(openLinked);
} else if (linked) {
  openLinked();
} else if (!remembered("welcome-seen")) {
  showWelcome(true);
}

"""Build docs/eval-report.html from the last eval run (data/processed/eval_results.parquet) and evals/history.csv.

    uv run python -m evals.run_eval && uv run python -m evals.report
"""

import html
from pathlib import Path

import pandas as pd

from evals.run_eval import HISTORY, RESULTS
from evals.stats import interval, paired_difference

OUT = Path("docs/eval-report.html")
PRODUCTION = "rewrite+hybrid+region"
STEPS = [  # (what was added, method with it, method without it)
    ("Region ranking on BM25", "bm25+region", "bm25"),
    ("Hybrid (BM25 + embeddings) instead of BM25 alone", "hybrid+region", "bm25+region"),
    ("Gemini query rewrite on top of hybrid", PRODUCTION, "hybrid+region"),
    ("Embeddings added to the rewrite + BM25 pipeline (what the model files cost us)", PRODUCTION, "rewrite+bm25+region"),
]
LIMITS = [
    "All 88 questions were written by Claude (30 from a need, 40 seeded from random catalog items, 13 with a period, 5 for the "
    "kab/kota fallback). No real user question is in the set yet, and real questions are messier.",
    "Labels came from keyword filters plus pooled judging of the methods' top 5, so a correct source no method returned is not in the labels.",
    "The intervals treat the 88 questions as a random sample. They are not: they describe this set only, and a difference "
    "inside the interval is noise.",
    "The BPS site-search baseline was measured once, on the first 70 questions, with the same labels.",
    "The rewrite is cached per question and prompt, so a rerun reproduces the numbers. A new prompt or model calls Gemini again.",
]
CSS = """
:root { --bg:#fcfcfb; --card:#fff; --ink:#0b0b0b; --muted:#52514e; --grid:#e8e7e3; --blue:#2a78d6; color-scheme: light dark; }
@media (prefers-color-scheme: dark) { :root { --bg:#141414; --card:#1c1c1b; --ink:#f2f2f0; --muted:#a8a7a1; --grid:#34332f; --blue:#5aa0f0; } }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1000px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:26px; margin:0 0 4px; } h2 { font-size:18px; margin:0 0 4px; }
.sub,.take { color:var(--muted); margin:0 0 12px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }
.tile,section { background:var(--card); border:1px solid var(--grid); border-radius:10px; padding:14px 16px; }
.tile .v { font-size:24px; font-weight:600; } .tile .l { color:var(--muted); font-size:13px; }
section { margin-top:16px; overflow-x:auto; }
table { border-collapse:collapse; font-size:13px; margin-top:8px; }
th,td { text-align:left; padding:4px 14px 4px 0; border-bottom:1px solid var(--grid); vertical-align:top; }
td.n,th.n { text-align:right; font-variant-numeric:tabular-nums; }
svg { max-width:100%; height:auto; } svg text { fill:var(--muted); font-size:12px; } svg .name { fill:var(--ink); }
svg .grid { stroke:var(--grid); } svg .bar { stroke:var(--blue); stroke-width:2; } svg .dot { fill:var(--blue); stroke:var(--card); stroke-width:2; }
ul { margin:6px 0 0; padding-left:20px; }
"""


def esc(value):
    return html.escape(str(value))


def table(frame, numeric=()):
    head = "".join(f'<th class="{"n" if c in numeric else ""}">{esc(c)}</th>' for c in frame.columns)
    body = "".join(
        "<tr>" + "".join(f'<td class="{"n" if c in numeric else ""}">{esc(v)}</td>' for c, v in row.items()) + "</tr>"
        for row in frame.to_dict("records")
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def section(title, takeaway, body):
    return f"<section><h2>{esc(title)}</h2><p class='take'>{esc(takeaway)}</p>{body}</section>"


def pct(value):
    return f"{value:.3f}"


def dot_chart(rows):
    """Recall@5 per method with its 95% interval; rows = [(method, recall, lo, hi)] best first."""
    left, right, top, step, width = 190, 60, 24, 30, 720
    plot = width - left - right
    height = top + step * len(rows) + 30
    x = lambda v: left + v * plot
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Recall@5 per method with 95% intervals">']
    for tick in (0, 0.25, 0.5, 0.75, 1):
        parts.append(f'<line class="grid" x1="{x(tick)}" x2="{x(tick)}" y1="{top - 8}" y2="{height - 26}"/>')
        parts.append(f'<text x="{x(tick)}" y="{height - 8}" text-anchor="middle">{tick:g}</text>')
    for i, (method, recall, lo, hi) in enumerate(rows):
        y = top + step * i + step / 2
        parts.append(f'<text class="name" x="{left - 10}" y="{y + 4}" text-anchor="end">{esc(method)}</text>')
        parts.append(f'<g><title>{esc(method)}: Recall@5 {pct(recall)} (95% interval {pct(lo)} to {pct(hi)})</title>'
                     f'<line class="bar" x1="{x(lo)}" x2="{x(hi)}" y1="{y}" y2="{y}"/><circle class="dot" cx="{x(recall)}" cy="{y}" r="6"/></g>')
        parts.append(f'<text x="{x(hi) + 8}" y="{y + 4}">{pct(recall)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build():
    results = pd.read_parquet(RESULTS)
    history = pd.read_csv(HISTORY, dtype=str).fillna("")
    golden = pd.read_csv("evals/golden_set.csv", dtype=str)
    by_method = {m: d.reset_index(drop=True) for m, d in results.groupby("method", sort=False)}
    if PRODUCTION not in by_method:
        raise SystemExit(f"{PRODUCTION} is not in the last run: run the eval with GEMINI_API_KEY set")
    prod = by_method[PRODUCTION]

    rows = []
    for method, df in by_method.items():
        lo, hi = interval(df["recall@5"])
        rows.append((method, df["recall@5"].mean(), lo, hi, df["mrr"].mean()))
    rows.sort(key=lambda r: -r[1])
    methods = pd.DataFrame([{"Method": m, "Recall@5": pct(r), "95% interval": f"{pct(lo)} to {pct(hi)}", "MRR": pct(mrr)}
                            for m, r, lo, hi, mrr in rows])

    steps = []
    for label, with_, without in STEPS:
        delta, (lo, hi) = paired_difference(by_method[with_]["recall@5"], by_method[without]["recall@5"])
        steps.append({"Step": label, "Change in Recall@5": f"{delta * 100:+.1f} points",
                      "95% interval": f"{lo * 100:+.1f} to {hi * 100:+.1f}",
                      "Read": "clearly better" if lo > 0 else "clearly worse" if hi < 0 else "within noise"})

    segments = []
    for column, label in (("source", "Question source"), ("type", "Target type")):
        g = prod.groupby(column).agg(n=("rank", "size"), hits=("recall@5", "sum"), mrr=("mrr", "mean")).reset_index()
        segments.append(table(pd.DataFrame({label: g[column], "Questions": g["n"], "Hits in top 5": g["hits"].astype(int),
                                            "Recall@5": (g["hits"] / g["n"]).map(pct), "MRR": g["mrr"].map(pct)}),
                             numeric=("Questions", "Hits in top 5", "Recall@5", "MRR")))
    misses = prod[~prod["recall@5"]][["question", "rank", "top1"]].rename(columns={"question": "Question", "rank": "Rank of the right source", "top1": "Top result"})
    misses["Rank of the right source"] = misses["Rank of the right source"].map(lambda r: "not in top 10" if pd.isna(r) else int(r))

    shown = history[history["method"].isin([PRODUCTION, "bps-search-keywords"])].rename(columns={
        "date": "Date", "source": "Run", "catalog_rows": "Catalog rows", "n": "Questions", "method": "Method", "recall5": "Recall@5", "mrr": "MRR"})
    shown["95% interval"] = [f"{float(lo):.3f} to {float(hi):.3f}" if lo else "not kept" for lo, hi in zip(history.loc[shown.index, "recall5_lo"], history.loc[shown.index, "recall5_hi"])]
    shown = shown[["Date", "Run", "Method", "Questions", "Catalog rows", "Recall@5", "95% interval", "MRR"]]

    best, lo, hi = prod["recall@5"].mean(), *interval(prod["recall@5"])
    baseline = history[history["method"] == "bps-search-keywords"].iloc[-1]
    tiles = [
        (f"{pct(best)}", f"Recall@5, {PRODUCTION} (95% interval {pct(lo)} to {pct(hi)})"),
        (pct(prod["mrr"].mean()), "MRR of the same method"),
        (baseline["recall5"], f"Recall@5 of BPS's own site search (keywords, {baseline['n']} questions)"),
        (str(len(golden)), "questions, all written by Claude"),
    ]
    body = "".join([
        f'<h1>Retrieval evaluation</h1><p class="sub">Does the right BPS source appear in the top 5? Last run: {esc(history.iloc[-1]["date"])}, '
        f'code {esc(history.iloc[-1]["source"])}, catalog {esc(history.iloc[-1]["catalog_rows"])} rows.</p>',
        '<div class="tiles">' + "".join(f'<div class="tile"><div class="v">{esc(v)}</div><div class="l">{esc(label)}</div></div>' for v, label in tiles) + "</div>",
        section("Methods compared", "Recall@5 with a 95% interval from resampling the questions. Overlapping intervals are not a difference.",
                dot_chart([(m, r, lo, hi) for m, r, lo, hi, _ in rows]) + table(methods, numeric=("Recall@5", "MRR"))),
        section("Did each step help?", "The same questions with and without the step, resampled together (paired).", table(pd.DataFrame(steps))),
        section(f"Where {PRODUCTION} works and where it does not", "By question source and by the type of source the question points at. Small groups move by a whole question at a time.", "".join(segments)),
        section("Questions it misses", f"{len(misses)} of {len(prod)} questions have no right source in the top 5.", table(misses) if len(misses) else ""),
        section("History", "Every eval run, from the first BPS site-search baseline. Runs before 2026-11-04 were saved as text only, so they have no interval.", table(shown, numeric=("Questions", "Catalog rows", "Recall@5", "MRR"))),
        section("Limits", "Read the numbers with these in mind.", "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in LIMITS) + "</ul>"),
    ])
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Retrieval evaluation</title><style>{CSS}</style></head><body><main>{body}</main></body></html>'


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(build())
    print(f"wrote {OUT}")

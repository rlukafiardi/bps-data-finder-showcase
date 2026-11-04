"""Score retrieval methods on evals/golden_set.csv: Recall@5 and MRR@10, per source and per target type.

A target is `type:domain:id`; SIMDASI targets use the table code (e.g. `simdasi:3273:4.1.3`).

    uv run python -m evals.run_eval [--smoke]

--smoke is the check after a catalog refresh: exit 1 when Recall@5 of rewrite+hybrid+region is below
SMOKE_MIN_RECALL.
"""

import argparse
import csv
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from evals.stats import interval
from src.config import SMOKE_MIN_RECALL
from src.retrieval.bm25 import BM25
from src.retrieval.dense import Dense, Hybrid
from src.retrieval.region_rank import RegionRank
from src.retrieval.rewrite import Rewriter, Rewritten

GOLDEN = Path("evals/golden_set.csv")
HISTORY = Path("evals/history.csv")  # one row per method per run; the report draws its history from it
RESULTS = Path("data/processed/eval_results.parquet")  # every question of the last run, for the report
CATALOG = Path("data/processed/catalog.parquet")
K = 10


def keys(row):
    """Target keys a catalog row answers to."""
    out = {f"{row['type']}:{row['domain']}:{row['source_id']}"}
    if row["type"] == "simdasi" and row["table_code"]:
        out.add(f"simdasi:{row['domain']}:{row['table_code']}")
    return out


def score(method, golden):
    out = []
    for gold in golden.to_dict("records"):
        targets = set(gold["targets"].split("|"))
        results = method.search(gold["question"], k=K).to_dict("records")
        rank = next((i + 1 for i, r in enumerate(results) if keys(r) & targets), None)
        out.append({
            "question": gold["question"],
            "source": gold["source"],
            "type": gold["targets"].split(":")[0],
            "rank": rank,
            "top1": f"{results[0]['type']}:{results[0]['domain']} {results[0]['title'][:60]}" if results else "",
        })
    df = pd.DataFrame(out)
    df["recall@5"] = df["rank"].le(5)
    df["mrr"] = 1 / df["rank"].fillna(float("inf"))
    return df


def summary(df, by):
    s = df.groupby(by)[["recall@5", "mrr"]].mean()
    s["n"] = df.groupby(by).size()
    return s


def check_targets(golden, catalog):
    """Targets missing from the catalog: a labelling error or a gap in the pull."""
    known = set().union(*(keys(r) for r in catalog.to_dict("records")))
    missing = [t for ts in golden["targets"] for t in ts.split("|") if t not in known]
    if missing:
        print("targets not in catalog:", ", ".join(missing))


def code_version():
    short = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "evals", "app"], capture_output=True, text=True, check=True).stdout.strip()
    return short + ("+dirty" if dirty else "")


def record(results, catalog_rows):
    """Save the questions of this run and add one history row per method."""
    pd.concat([df.assign(method=name) for name, df in results.items()]).to_parquet(RESULTS, index=False)
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="") as f:
        out = csv.writer(f)
        if new:
            out.writerow(["date", "source", "catalog_rows", "n", "method", "recall5", "recall5_lo", "recall5_hi", "mrr"])
        for name, df in results.items():
            lo, hi = interval(df["recall@5"])
            out.writerow([date.today(), code_version(), catalog_rows, len(df), name,
                          round(df["recall@5"].mean(), 3), round(lo, 3), round(hi, 3), round(df["mrr"].mean(), 3)])


def main(smoke):
    load_dotenv(".env")
    golden = pd.read_csv(GOLDEN, dtype=str)
    catalog = pd.read_parquet(CATALOG)
    print(f"golden rows: {len(golden)} ({golden['source'].value_counts().to_dict()}), catalog rows: {len(catalog)}")
    check_targets(golden, catalog)
    bm25, dense = BM25(catalog), Dense(catalog)
    hybrid = Hybrid(bm25, dense)
    methods = {
        "bm25": bm25,
        "bm25+region": RegionRank(bm25),
        "dense": dense,
        "dense+region": RegionRank(dense),
        "hybrid+region": RegionRank(hybrid),
    }
    if os.environ.get("GEMINI_API_KEY"):
        rewriter = Rewriter()
        methods["rewrite+bm25+region"] = Rewritten(RegionRank(bm25), rewriter)
        methods["rewrite+hybrid+region"] = Rewritten(RegionRank(hybrid), rewriter)
    results = {}
    for name, method in methods.items():
        df = results[name] = score(method, golden)
        print(f"\n== {name}")
        print(summary(df.assign(all="ALL"), "all").round(3).to_string())
        print(summary(df, "source").round(3).to_string())
        print(summary(df, "type").round(3).to_string())
        misses = df[df["recall@5"].eq(False)]
        for m in misses.itertuples():
            print(f"  miss (rank {m.rank}): {m.question!r} -> top1 {m.top1}")
    record(results, len(catalog))
    if smoke:
        checked = results["rewrite+hybrid+region"]["recall@5"].mean() if "rewrite+hybrid+region" in results else None
        if checked is None:
            sys.exit("smoke check needs GEMINI_API_KEY: rewrite+hybrid+region did not run")
        if checked < SMOKE_MIN_RECALL:
            sys.exit(f"SMOKE FAIL: Recall@5 {checked:.3f} is below {SMOKE_MIN_RECALL}")
        print(f"\nsmoke ok: Recall@5 {checked:.3f} >= {SMOKE_MIN_RECALL}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    main(parser.parse_args().smoke)

"""Search API for the BPS data finder: question -> top 5 BPS sources with public links.

    ALLOWED_ORIGINS=http://localhost:8080 uv run uvicorn app.main:app --port 8000
"""

import json
import os
import time
from collections import defaultdict, deque
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.retrieval.bm25 import BM25
from src.retrieval.dense import Dense, Hybrid
from src.retrieval.coverage import no_match
from src.retrieval.period import latest_year
from src.retrieval.region_rank import RegionRank, close_matches
from src.retrieval.regions import domains, find_regions
from src.retrieval.rewrite import Rewriter
from src.values.bps import Busy, BpsError
from src.values.tables import mark_regions, simdasi_table, static_table, var_table

CATALOG = "data/processed/catalog.parquet"
SERVING = "data/processed/serving"  # indexes written by src.retrieval.save_index; they make the start faster
PER_CLIENT_PER_MINUTE = 20
# all visitors together, so a script with many addresses cannot burn the free tier or flood the logs; sized on a
# laptop (search 0.04-0.7 s, value waits for a BPS slot), to re-check against Cloud Run latency
TOTAL_PER_MINUTE = {"search": 120, "value": 60, "feedback": 200}
MAX_TRACKED_CLIENTS = 10000
TYPE_LABELS = {
    "var": "Tabel angka",
    "statictable": "Tabel arsip",
    "simdasi": "Daerah Dalam Angka",
    "publication": "Publikasi",
    "pressrelease": "Berita Resmi",
}

catalog = pd.read_parquet(CATALOG)
by_id = catalog.set_index("doc_id", drop=False)
search = RegionRank(Hybrid(BM25(catalog, saved=f"{SERVING}/bm25"), Dense(catalog, saved=f"{SERVING}/dense")))
rewriter = Rewriter(serving=True)
recent = defaultdict(deque)
total_recent = defaultdict(deque)

app = FastAPI(title="BPS Data Finder")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8080").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
def invalid_request(request, exc):
    # the default reply echoes the input, and a body of NaN cannot be encoded back (500)
    return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, status_code=422)


def full(calls, limit, now):
    while calls and calls[0] < now - 60:
        calls.popleft()
    if len(calls) >= limit:
        return True
    calls.append(now)
    return False


def over_limit(request, kind):
    # Cloud Run appends the address it saw to X-Forwarded-For; every entry before it was sent by the caller
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[-1].strip()
    if len(recent) > MAX_TRACKED_CLIENTS:
        recent.clear()  # windows are one minute long, so forgetting them costs at most one extra minute
    now = time.monotonic()
    return full(recent[ip], PER_CLIENT_PER_MINUTE, now) or full(total_recent[kind], TOTAL_PER_MINUTE[kind], now)


def result(row):
    return {
        "doc_id": row["doc_id"],
        "type": row["type"],
        "type_label": TYPE_LABELS[row["type"]],
        "title": row["title"],
        "region": domains()[row["domain"]]["name"],
        "date": row["date"],
        "years": row["years"].tolist() if row["years"] is not None else None,  # SIMDASI only, numpy array
        "latest_year": latest_year(row),  # the page tags tables whose newest year is old
        "table_code": row["table_code"],
        "url": row["url"],
        "url_built": row["url_built"],
    }


@app.get("/api/health")
def api_health():
    return {"ok": True}  # a scheduler pings this to keep one instance warm; it takes no BPS or Gemini slot


@app.get("/api/search")
def api_search(request: Request, q: str = Query(min_length=2, max_length=200)):
    if over_limit(request, "search"):
        raise HTTPException(429, "Terlalu banyak pencarian. Coba lagi sebentar.")
    rewrite = rewriter.rewrite_or_none(q)
    text = " ".join(p for p in (q, rewrite["query"], rewrite["region"]) if p) if rewrite else q
    hits = close_matches(search.search(text, k=5))
    nothing = bool(len(hits)) and no_match(text, hits.iloc[0])
    hits = hits.astype(object).where(hits.notna(), None)
    # question text only, no IP: real queries become the next golden set
    print(json.dumps({"event": "search", "q": q, "rewrite": rewrite is not None, "no_match": nothing, "results": hits["doc_id"].tolist()}), flush=True)
    return {
        "question": q,
        "rewrite": rewrite,
        "regions": [{"id": d, "name": domains()[d]["name"]} for d in find_regions(text)],
        "no_match": nothing,  # the best result has almost none of the question's words: probably no BPS data on it
        "results": [result(r) for r in hits.to_dict("records")],
    }


class Feedback(BaseModel):
    q: str = Field(min_length=2, max_length=200)
    doc_id: str = Field(max_length=120)
    verdict: Literal["ya", "tidak"]


@app.post("/api/feedback", status_code=204)
def api_feedback(request: Request, body: Feedback):
    """Did this result match the question? Logged like searches (no IP): the labels for the next golden set."""
    if body.doc_id not in by_id.index:
        raise HTTPException(404, "Hasil tidak ditemukan.")
    if over_limit(request, "feedback"):
        raise HTTPException(429, "Terlalu banyak permintaan. Coba lagi sebentar.")
    print(json.dumps({"event": "feedback", "q": body.q, "doc_id": body.doc_id, "verdict": body.verdict}), flush=True)


@app.get("/api/value")
def api_value(
    request: Request,
    doc_id: str = Query(max_length=120),
    period: str | None = Query(None, max_length=10),
    regions: str = Query("", max_length=60),
):
    """The table behind one search result, as BPS gives it. Publications and press releases are links only."""
    if doc_id not in by_id.index:
        raise HTTPException(404, "Tabel tidak ditemukan.")
    if over_limit(request, "value"):
        raise HTTPException(429, "Terlalu banyak permintaan. Coba lagi sebentar.")
    row = by_id.loc[doc_id]
    try:
        if row["type"] == "var":
            table = var_table(row["domain"], row["source_id"], period)
        elif row["type"] == "simdasi":
            table = simdasi_table(row["domain"], row["source_id"], [int(y) for y in row["years"]], period)
        elif row["type"] == "statictable":
            table = static_table(row["domain"], row["source_id"])
        else:
            raise HTTPException(400, "Publikasi dan Berita Resmi Statistik hanya berupa tautan ke BPS.")
    except ValueError:
        raise HTTPException(400, "Periode tidak tersedia.")
    except Busy:
        raise HTTPException(429, "Sedang ramai. Coba lagi sebentar.")
    except BpsError as e:
        print(json.dumps({"event": "bps_error", "doc_id": doc_id, "error": str(e)}), flush=True)
        raise HTTPException(502, "BPS belum menjawab. Coba lagi nanti.")
    table["fetched_at"] = pd.Timestamp(table["fetched_at"], unit="s", tz="UTC").isoformat(timespec="seconds")
    print(json.dumps({"event": "value", "doc_id": doc_id, "period": table["period"]}), flush=True)
    return {
        "doc_id": doc_id,
        "type": row["type"],
        "url": row["url"],
        **mark_regions(table, [d for d in regions.split(",") if d in domains()]),
    }

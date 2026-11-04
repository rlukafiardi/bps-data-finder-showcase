"""Pull the BPS WebAPI catalog into data/raw/catalog/, one JSON file per page.

1. national + all provinces: tables from the search endpoint (100 rows/page, more tables than the list
   endpoints); publications and press releases from the list endpoint per year (search returns
   "list-not-available" for them, or for publications outside 0000)
2. SIMDASI (Dalam Angka) table lists for all provinces and kab/kota
3. var lists with notes for NOTES_DOMAINS (list endpoints are fixed at 10 rows/page)
4. a second search pass at 50 rows/page into search50/ for domains whose search came back short: the
   paging is unstable and each pass drops a different set (one pass at 100 missed 8.1% overall)

Resumable: a page already on disk is never fetched again. Stops at the first 401/403, after
repeated 429/5xx, or at the wall-clock limit; rerun to continue.

Refresh (the pages on disk are kept until their replacement arrives, so an interrupted refresh never leaves holes):
  --refresh recent  the publication and press-release lists of the current year, every domain (~5 min)
  --refresh all     every page again; resumable through data/raw/catalog/refresh_started, whose time is the
                    cutoff: a page older than it is fetched again, a newer one is skipped (hours at 3 s a request)

    uv run python -m src.ingestion.pull_catalog [--minutes 120] [--refresh recent|all]
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(".env")
KEY = os.environ["BPS_API_KEY"]
BASE = "https://webapi.bps.go.id/v1"
RAW = Path("data/raw/catalog")
LOG = RAW / "requests.log"

YEARS = [date.today().year - 1, date.today().year]  # publications and press releases; older year folders stay on disk
NOTES_DOMAINS = ["0000", "3200"]
DELAY_S = 3.0  # BPS returns 429 after ~20 requests/minute
RATE_LIMIT_WAIT_S = 65
RETRIES = 3
MARKER = RAW / "refresh_started"
cutoff = None  # epoch seconds: a cached page older than this is fetched again



class Stop(Exception):
    pass


def log(path, status):
    with LOG.open("a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}\t{status}\t{path}\n")


def get(client, path, params, out):
    """Fetch path (with {key}) to out unless cached; return the parsed JSON, or None if gone."""
    if out.exists() and (cutoff is None or out.stat().st_mtime >= cutoff):
        return json.loads(out.read_text())
    for attempt in range(RETRIES):
        time.sleep(DELAY_S)
        try:
            resp = client.get(path.format(key=KEY), params=params)
            status = resp.status_code
        except httpx.TransportError as e:
            resp, status = None, type(e).__name__
        log(f"{path}?{params}", status)
        if status == 200:
            body = resp.json()
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(body, ensure_ascii=False))
            tmp.replace(out)  # a refresh must not leave a half-written page where a good one was
            return body
        if status in (401, 403):
            raise Stop(f"HTTP {status} on {path}")
        if status in (404, 410):
            return None
        if status == 429:
            time.sleep(int(resp.headers.get("retry-after", RATE_LIMIT_WAIT_S)))
        else:
            time.sleep(DELAY_S * 2 ** (attempt + 1))
    raise Stop(f"still failing after {RETRIES} tries ({status}) on {path}")


def pages(body):
    data = body.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get("pages", 1)
    return 0  # "data-availability": "list-not-available"


def pull_pages(client, path, params, folder, deadline):
    first = get(client, path, {"page": 1, **params}, folder / "p0001.json")
    n = pages(first) if first else 0
    for page in range(2, n + 1):
        if time.monotonic() > deadline:
            raise Stop("wall-clock limit reached, rerun to resume")
        get(client, path, {"page": page, **params}, folder / f"p{page:04d}.json")
    return n


def search_short(domain):
    pages = [json.loads(p.read_text())["data"] for p in sorted((RAW / "search" / domain / "tablestatistic").glob("p*.json"))]
    if not pages or not pages[0]:
        return False
    return len({r["url"] for p in pages for r in p[1]}) < pages[0][0]["total"]


def pull_lists(client, domain, years, deadline):
    for model in ["publication", "pressrelease"]:
        for year in years:
            path = f"/api/list/model/{model}/domain/{domain}/key/{{key}}"
            n = pull_pages(client, path, {"year": year}, RAW / domain / model / str(year), deadline)
            print(f"{model} {domain} {year}: {n} pages", flush=True)


def main(minutes, refresh=None):
    global cutoff
    deadline = time.monotonic() + minutes * 60
    RAW.mkdir(parents=True, exist_ok=True)
    if refresh == "recent":
        cutoff = time.time()
    elif refresh == "all":
        MARKER.touch()  # keeps its first time when a refresh is resumed
        cutoff = MARKER.stat().st_mtime
    with httpx.Client(
        base_url=BASE, timeout=60, headers={"User-Agent": "bps-data-finder/0.1 (personal research)"}
    ) as client:
        provs = get(client, "/api/domain/type/prov/key/{key}", {}, RAW / "domains_prov.json")
        provinces = [d["domain_id"] for d in provs["data"][1]]

        if refresh == "recent":
            for domain in ["0000"] + provinces:
                pull_lists(client, domain, YEARS[-1:], deadline)
            return

        for domain in ["0000"] + provinces:
            path = f"/searching/content/domain/{domain}/model/tablestatistic/key/{{key}}"
            n = pull_pages(client, path, {"perpage": 100}, RAW / "search" / domain / "tablestatistic", deadline)
            print(f"search {domain} tablestatistic: {n} pages", flush=True)
            pull_lists(client, domain, YEARS, deadline)

        # one list of all kab/kota: `kabbyprov?prov=` started returning Aceh for every province (2026-11-02)
        kabs = get(client, "/api/domain/type/kab/key/{key}", {}, RAW / "domains_kab.json")
        kab_ids = [d["domain_id"] for d in kabs["data"][1]]
        for prov in provinces:
            prov_kabs = [k for k in kab_ids if k[:2] == prov[:2]]
            for domain in [prov] + prov_kabs:
                if time.monotonic() > deadline:
                    raise Stop("wall-clock limit reached, rerun to resume")
                get(
                    client,
                    f"/api/interoperabilitas/datasource/simdasi/id/23/wilayah/{domain}000/key/{{key}}",
                    {},
                    RAW / "simdasi" / f"{domain}.json",
                )
            print(f"simdasi {prov}: {len(prov_kabs) + 1} table lists", flush=True)

        for domain in NOTES_DOMAINS:
            path = f"/api/list/model/var/domain/{domain}/key/{{key}}"
            n = pull_pages(client, path, {}, RAW / domain / "var" / "all", deadline)
            print(f"var notes {domain}: {n} pages", flush=True)

        for domain in ["0000"] + provinces:
            if search_short(domain):
                path = f"/searching/content/domain/{domain}/model/tablestatistic/key/{{key}}"
                n = pull_pages(client, path, {"perpage": 50}, RAW / "search50" / domain / "tablestatistic", deadline)
                print(f"search50 {domain}: {n} pages", flush=True)
    if refresh == "all":
        MARKER.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=120)
    parser.add_argument("--refresh", choices=["recent", "all"])
    args = parser.parse_args()
    try:
        main(args.minutes, args.refresh)
    except Stop as e:
        print("STOP:", e, file=sys.stderr)
        sys.exit(1)

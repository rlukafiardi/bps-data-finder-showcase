"""Baseline: BPS's own search (`/v1/searching/content`) on the golden questions, scored like run_eval.

Two variants, results merged by BPS's `relevance`, responses cached in data/raw/baseline/:
- literal: the whole question as the keyword, on the site of the first region it names (national if none),
  for tables, publications and press releases.
- keywords: a patient user. Filler words, numbers and the region name are dropped; if nothing comes back,
  the last word is dropped and the search retried (up to 3 times). Tables on the region's site,
  publications on the national site (publication search is empty elsewhere); press-release search
  always comes back empty, so it is skipped.

    uv run python -m evals.site_search_baseline
"""

import base64
import hashlib

import httpx
import pandas as pd

from evals.run_eval import CATALOG, GOLDEN, K, score, summary
from src.ingestion.pull_catalog import BASE, RAW, get
from src.retrieval.regions import domains, find_regions, normalize

MODELS = {"tablestatistic": None, "publication": "publication", "pressrelease": "pressrelease"}
TABLE_TYPES = {"1": "statictable", "2": "var", "3": "simdasi"}
FILLER = {"per", "tiap", "di", "dan", "yang", "berapa", "menurut", "semua", "data", "apa", "terbaru", "provinsi",
          "kabupaten", "kab", "kota", "the", "by", "of", "in"}
RETRIES = 3


def to_row(model, r, domain):
    if model == "tablestatistic":
        token = r["url"].split("/statistics-table/")[1].split("/")[1]
        parts = base64.b64decode(token + "=" * (-len(token) % 4)).decode().split("#")
        return {"type": TABLE_TYPES.get(parts[1], "other"), "domain": domain, "source_id": parts[0], "table_code": None,
                "title": r["title"], "relevance": r.get("relevance")}
    return {"type": MODELS[model], "domain": domain, "source_id": str(r["id"]), "table_code": None,
            "title": r["title"], "relevance": r.get("relevance")}


class SiteSearch:
    def __init__(self, client):
        self.client = client
        cat = pd.read_parquet(CATALOG, columns=["type", "domain", "source_id", "table_code"])
        simdasi = cat[cat["type"] == "simdasi"]
        # golden SIMDASI targets may use the table code, which search rows do not carry
        self.table_codes = dict(zip(zip(simdasi["domain"], simdasi["source_id"]), simdasi["table_code"]))

    def query(self, domain, model, words, k):
        keyword = "+".join(words)
        path = f"/searching/content/domain/{domain}/model/{model}/key/{{key}}"
        name = hashlib.sha256(f"{domain}|{model}|{keyword}".encode()).hexdigest()[:16]
        body = get(self.client, path, {"page": 1, "perpage": k, "keyword": keyword}, RAW.parent / "baseline" / f"{name}.json")
        data = body.get("data") if body else None
        return [to_row(model, r, domain) for r in data[1]] if isinstance(data, list) and len(data) == 2 else []

    def search(self, question, k=K):
        regions = find_regions(question)
        domain = regions[0] if regions else "0000"
        rows = []
        for model in MODELS:
            rows += self.query(domain, model, question.split(), k)
        return self.finish(rows, k)

    def finish(self, rows, k):
        for r in rows:
            if r["type"] == "simdasi":
                r["table_code"] = self.table_codes.get((r["domain"], r["source_id"]))
        rows.sort(key=lambda r: -float(r["relevance"] or 0))
        return pd.DataFrame(rows[:k], columns=["type", "domain", "source_id", "table_code", "title", "relevance"])


class KeywordSearch(SiteSearch):
    def search(self, question, k=K):
        regions = find_regions(question)
        domain = regions[0] if regions else "0000"
        region_words = {w for d in regions for a in domains()[d]["aliases"] for w in a.split()}
        words = [w for w in normalize(question).split() if w not in FILLER and w not in region_words and not w.isdigit()]
        rows = []
        for model, site in (("tablestatistic", domain), ("publication", "0000")):
            for n in range(len(words), max(len(words) - RETRIES, 0) - 1, -1):
                found = self.query(site, model, words[:n], k) if n else []
                if found:
                    rows += found
                    break
        return self.finish(rows, k)


def main():
    golden = pd.read_csv(GOLDEN, dtype=str, keep_default_na=False)
    with httpx.Client(base_url=BASE, timeout=60, headers={"User-Agent": "bps-data-finder/0.1 (personal research)"}) as client:
        for name, method in (("literal", SiteSearch(client)), ("keywords", KeywordSearch(client))):
            df = score(method, golden)
            print(f"== bps site search, {name}")
            print(summary(df.assign(all="ALL"), "all").round(3).to_string())
            print(summary(df, "source").round(3).to_string())
            print(summary(df, "type").round(3).to_string())


if __name__ == "__main__":
    main()

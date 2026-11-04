"""Flatten data/raw/catalog/ into data/processed/catalog.parquet, one row per catalog item.

Sources (see pull_catalog.py): search pages for tables, list pages for publications and press
releases, SIMDASI table lists, and var lists whose notes are joined onto the var rows.

    uv run python -m src.ingestion.build_catalog
"""

import base64
import html
import json
import re
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/catalog")
OUT = Path("data/processed/catalog.parquet")
QUARANTINE = Path("data/processed/catalog_quarantine.parquet")

TABLE_TYPES = {"1": "statictable", "2": "var", "3": "simdasi"}  # search `category`
TAG = re.compile(r"<[^>]+>")


def clean(value):
    if value is None:
        return ""
    return " ".join(TAG.sub(" ", html.unescape(str(value))).split())


def page_rows(pattern):
    for path in sorted(RAW.glob(pattern)):
        data = json.loads(path.read_text()).get("data")
        if isinstance(data, list) and len(data) == 2:
            yield path, data[1]


def search_tables():
    for path, rows in page_rows("search*/*/tablestatistic/p*.json"):  # search/ and the second pass search50/
        domain = path.parts[-3]
        for r in rows:
            # url: .../statistics-table/{category}/{base64 id}/slug; for var and statictable the id is "<id>#<category>"
            token = r["url"].split("/statistics-table/")[1].split("/")[1]
            decoded = base64.b64decode(token + "=" * (-len(token) % 4)).decode()
            source_id = decoded.split("#")[0]
            yield {
                "type": TABLE_TYPES.get(r["category"], f"table{r['category']}"),
                "domain": domain,
                "source_id": source_id,
                "title": clean(r["title"]),
                "text_parts": [r.get("subject"), r.get("body")],
                "date": r.get("updated"),
                "url": r["url"],
            }


def listed(model, id_field, text_fields):
    for path, rows in page_rows(f"*/{model}/*/p*.json"):
        domain = path.parts[-4]
        for r in rows:
            yield {
                "type": model,
                "domain": domain,
                "source_id": str(r.get(id_field) or ""),
                "title": clean(r.get("title")),
                "text_parts": [r.get(f) for f in text_fields],
                "date": r.get("rl_date"),
                "pdf": r.get("pdf"),
            }


def simdasi_lists():
    for path in sorted((RAW / "simdasi").glob("*.json")):
        domain = path.stem
        for r in json.loads(path.read_text())["data"][1].get("data") or []:
            yield {
                "type": "simdasi",
                "domain": domain,
                "source_id": r["id_tabel"],
                "title": clean(r.get("judul")),
                "text_parts": [r.get("judul_en"), r.get("bab"), r.get("subject")],
                "date": r.get("latest_update"),
                "years": r.get("ketersediaan_tahun"),
                "table_code": r.get("kode_tabel"),
            }


def listed_vars():
    """var rows from the list endpoint, where pulled: they fill tables the search paging dropped."""
    for path, rows in page_rows("*/var/all/p*.json"):
        domain = path.parts[-4]
        for r in rows:
            yield {
                "type": "var",
                "domain": domain,
                "source_id": str(r["var_id"]),
                "title": clean(r.get("title")),
                "text_parts": [r.get("sub_name")],
            }


def sites():
    out = {"0000": "https://www.bps.go.id"}
    for path in [RAW / "domains_prov.json", RAW / "domains_kab.json"]:
        for d in json.loads(path.read_text())["data"][1]:
            out[d["domain_id"]] = d["domain_url"].rstrip("/")
    return out


def built_link(row, site):
    """Link for rows without one from BPS search, or None.

    Publication links open the right page. Press-release links need a slug after the id since early November
    2026 (without it bps.go.id answers 404; any slug works, the real one is used). A Dalam Angka link uses the
    token form of the 5,271 national and province links BPS gave us (id#3#domain). For kab/kota it is
    unchecked (BPS's firewall challenges headless Chrome there), and the 3 dynamic tables search never listed
    fail to load on bps.go.id, so those rows get no link."""
    date = str(row["date"])[:10].replace("-", "/")
    if row["type"] == "publication":
        return f"{site}/id/publication/{date}/{row['source_id']}"
    if row["type"] == "pressrelease":
        return f"{site}/id/pressrelease/{date}/{row['source_id']}/{slug(row['title'])}.html"
    if row["type"] == "simdasi" and row["domain"].endswith("00"):
        return f"{site}/id/statistics-table/3/{b64(row['source_id'] + '#3#' + row['domain'])}/{slug(row['title'])}.html"
    return None


def slug(title):
    return "-".join(re.findall(r"[a-z0-9]+", title.lower()))[:80]


def b64(text):
    return base64.b64encode(text.encode()).decode().rstrip("=")


def var_notes():
    notes = {}
    for path, rows in page_rows("*/var/all/p*.json"):
        domain = path.parts[-4]
        for r in rows:
            notes[(domain, str(r["var_id"]))] = " | ".join(
                p for p in (clean(r.get("def")), clean(r.get("notes")), clean(r.get("unit"))) if p
            )
    return notes


def main():
    rows = [
        *simdasi_lists(),  # first, so its table_code and years win the dedupe against search rows
        *search_tables(),  # before listed_vars, so search rows keep their url in the dedupe
        *listed_vars(),
        *listed("publication", "pub_id", ["abstract", "subject_csa"]),
        *listed("pressrelease", "brs_id", ["subj", "abstract"]),
    ]
    df = pd.DataFrame(rows)
    df["text_parts"] = df["text_parts"].map(lambda parts: " | ".join(p for p in map(clean, parts) if p))
    df = df.rename(columns={"text_parts": "body"})
    notes = var_notes()
    df["notes"] = [notes.get((d, i), "") if t == "var" else "" for t, d, i in zip(df["type"], df["domain"], df["source_id"])]
    df["doc_id"] = df["type"] + ":" + df["domain"] + ":" + df["source_id"]

    bad = (df["source_id"] == "") | (df["title"] == "")
    df[bad].to_parquet(QUARANTINE, index=False)
    out = df[~bad].groupby("doc_id", as_index=False).first()  # simdasi: list row + search row with its url
    site = sites()
    out["url_built"] = out["url"].isna()
    out.loc[out["url_built"], "url"] = [built_link(r, site[r["domain"]]) for r in out[out["url_built"]].to_dict("records")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)

    print(out.groupby(["type"]).agg(rows=("doc_id", "size"), domains=("domain", "nunique")).to_string())
    print(f"\nrows: {len(out)}, quarantined: {int(bad.sum())}, merged duplicates: {int((~bad).sum()) - len(out)}")
    print(f"var rows with notes: {(out['notes'] != '').sum()}")
    print("built links (not from BPS search):", out[out["url_built"]].groupby("type").size().to_dict())
    print("rows without a link:", out[out["url"].isna()].groupby("type").size().to_dict())


if __name__ == "__main__":
    main()

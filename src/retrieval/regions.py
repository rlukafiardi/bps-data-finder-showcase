"""BPS domain codes with their names and aliases, and lookup of region mentions in a question."""

import json
import re
from functools import cache
from pathlib import Path

RAW = Path("data/raw/catalog")

PROVINCE_ALIASES = {
    "1100": ["nad"], "1200": ["sumut"], "1300": ["sumbar"], "1600": ["sumsel"],
    "1900": ["babel", "bangka belitung", "kepulauan bangka belitung"], "2100": ["kepri", "kepulauan riau"],
    "3100": ["dki", "jakarta"], "3200": ["jabar"], "3300": ["jateng"], "3400": ["diy", "jogja", "yogyakarta"],
    "3500": ["jatim"], "5200": ["ntb"], "5300": ["ntt"], "6100": ["kalbar"], "6200": ["kalteng"],
    "6300": ["kalsel"], "6400": ["kaltim"], "6500": ["kaltara"], "7100": ["sulut"], "7200": ["sulteng"],
    "7300": ["sulsel"], "7400": ["sultra"], "7600": ["sulbar"], "8200": ["malut"], "9100": ["papua barat"],
}
PROVINCE_ENGLISH = {
    "1200": "north sumatra", "1300": "west sumatra", "1600": "south sumatra",
    "1900": "bangka belitung islands", "2100": "riau islands", "3200": "west java", "3300": "central java",
    "3400": "special region of yogyakarta", "3500": "east java", "5200": "west nusa tenggara",
    "5300": "east nusa tenggara", "6100": "west kalimantan", "6200": "central kalimantan",
    "6300": "south kalimantan", "6400": "east kalimantan", "6500": "north kalimantan", "7100": "north sulawesi",
    "7200": "central sulawesi", "7300": "south sulawesi", "7400": "southeast sulawesi", "7600": "west sulawesi",
    "8200": "north maluku", "9100": "west papua",
}
NATIONAL_WORDS = ["indonesia", "nasional"]


def normalize(text):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


@cache
def domains():
    """{domain_id: {"name": str, "level": "national" | "prov" | "kab" | "kota", "aliases": [str]}}"""
    out = {"0000": {"name": "Indonesia", "level": "national", "aliases": NATIONAL_WORDS}}
    for d in json.loads((RAW / "domains_prov.json").read_text())["data"][1]:
        name = normalize(d["domain_name"])
        out[d["domain_id"]] = {
            "name": d["domain_name"], "level": "prov",
            "aliases": [
                name, f"provinsi {name}", f"{name} province",
                *PROVINCE_ALIASES.get(d["domain_id"], []),
                *([PROVINCE_ENGLISH[d["domain_id"]]] if d["domain_id"] in PROVINCE_ENGLISH else []),
            ],
        }
    if (RAW / "domains_kab.json").exists():
        for d in json.loads((RAW / "domains_kab.json").read_text())["data"][1]:
            name = normalize(d["domain_name"])
            if int(d["domain_id"][2:]) >= 71:  # BPS codes: xx01-xx69 kabupaten, xx71+ kota
                level, label, aliases = "kota", f"Kota {d['domain_name']}", [name, f"kota {name}", f"{name} city"]
            else:
                level, label = "kab", f"Kabupaten {d['domain_name']}"
                aliases = [name, f"kabupaten {name}", f"kab {name}", f"{name} regency"]
            out[d["domain_id"]] = {"name": label, "level": level, "aliases": aliases}
    return out


def find_regions(question):
    """Domain ids whose alias appears in the question, longest alias first, overlaps removed.

    A bare name shared by a kabupaten and a kota ("bandung") returns both.
    """
    q = f" {normalize(question)} "
    matches = sorted(
        ((alias, dom) for dom, d in domains().items() for alias in d["aliases"] if f" {alias} " in q),
        key=lambda m: -len(m[0]),
    )
    taken, found = [], []  # (start, end, alias)
    for alias, dom in matches:
        start = q.index(f" {alias} ")
        end = start + len(alias) + 2
        if any(start < e and s < end and alias != a for s, e, a in taken):
            continue  # inside a longer match, e.g. "bandung" within "kota bandung"
        taken.append((start, end, alias))
        found.append(dom)
    return list(dict.fromkeys(found))


def strip_regions(text, region_ids):
    """The text without the names of the given regions, longest alias first."""
    q = f" {normalize(text)} "
    for alias in sorted({a for d in region_ids for a in domains()[d]["aliases"]}, key=len, reverse=True):
        q = q.replace(f" {alias} ", " ")
    return " ".join(q.split())

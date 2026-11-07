"""Region-aware ranking on top of a base retriever.

No region in the question: national (0000) only. Regions named: only those domains, their province and
national are searched, ranked in that order of preference. Kab/kota names are removed from the text that
is scored: every Dalam Angka table of a kab/kota repeats its name, which put off-topic tables of that
kab/kota above the province table "menurut Kabupaten/Kota" that answers the question. Province and
national names stay: they are part of the titles that answer ("Statistik Indonesia", "Provinsi Sumatera
Utara Dalam Angka"). When the question names a month, quarter or year, titles that agree are boosted and
titles that name a different one are demoted (see period.py): BM25 cannot tell "Januari 2025" from "Juli 2025".
"""

from src.retrieval.period import factor, of_row, periods
from src.retrieval.regions import domains, find_regions, strip_regions

CANDIDATES = 300
WEIGHTS = {"own": 1.0, "province": 0.85, "national": 0.7}
# the API shows only results scoring at least this share of the best one. On the 88 golden questions it keeps Recall@5 at 0.977
# and cuts the average from 5.0 to 4.4 results; a question with one close match ("tambang ilegal kalimantan timur") shows 2
MIN_SCORE_SHARE = 0.7


def close_matches(hits):
    """Hits scoring at least MIN_SCORE_SHARE of the best one (the best always stays). Scores are rank-based, so a weak list
    has a clear drop after its real matches; this cuts after it."""
    return hits[hits["score"] >= hits["score"].max() * MIN_SCORE_SHARE]


def allowed_domains(region_ids):
    if not region_ids:
        return {"0000": 1.0}
    out = {"0000": WEIGHTS["national"]}
    for d in region_ids:
        if d == "0000":
            continue
        province = d[:2] + "00"
        if province != d:
            out[province] = max(out.get(province, 0), WEIGHTS["province"])
        out[d] = WEIGHTS["own"]
    if "0000" in region_ids:
        out["0000"] = WEIGHTS["own"]
    return out


class RegionRank:
    def __init__(self, base):
        self.base = base

    def search(self, question, k=5):
        region_ids = find_regions(question)
        weights = allowed_domains(region_ids)
        kab_kota = [d for d in region_ids if domains()[d]["level"] in ("kab", "kota")]
        hits = self.base.search(strip_regions(question, kab_kota), k=CANDIDATES, domains=set(weights))
        hits = hits[hits["domain"].isin(weights)]  # BM25 can fill k with masked, zero-score rows
        hits = hits.assign(score=hits["score"] * hits["domain"].map(weights))
        asked = periods(question)
        if any(asked.values()):
            hits = hits.assign(score=hits["score"] * [factor(asked, of_row(r)) for r in hits.to_dict("records")])
        return hits.sort_values("score", ascending=False).head(k)

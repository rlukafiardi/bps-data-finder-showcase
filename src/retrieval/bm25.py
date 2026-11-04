"""BM25 over the catalog: title, region name, body, notes and table code as one text per row."""

import re

import bm25s
import numpy as np

from src.retrieval.regions import domains

STOPWORDS = {"dan", "di", "yang", "menurut", "dengan", "atau", "dari", "ke", "per", "pada", "the", "of", "and", "by", "in"}
TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text):
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


def doc_text(row):
    region = domains().get(row["domain"], {}).get("name", "")
    return " ".join(str(p) for p in (row["title"], region, row["body"], row["notes"], row["table_code"]) if p)


TITLE_WEIGHT = 5  # times the title is counted: BM25 divides by length, so a long abstract buried it (flat from 5 to 12, worse at 20)


def bm25_text(row):
    return " ".join([doc_text(row)] + [row["title"]] * (TITLE_WEIGHT - 1))


class BM25:
    def __init__(self, catalog):
        self.catalog = catalog.reset_index(drop=True)
        self.model = bm25s.BM25()
        self.model.index([tokenize(bm25_text(r)) for r in self.catalog.to_dict("records")], show_progress=False)

    def search(self, question, k=5, domains=None):
        """Top-k catalog rows with a `score` column; `domains` limits scoring to those domain ids."""
        tokens = tokenize(question)
        if not tokens:
            return self.catalog.iloc[0:0].assign(score=[])
        mask = self.catalog["domain"].isin(domains).to_numpy(dtype=float) if domains else None
        idx, scores = self.model.retrieve([tokens], k=k, show_progress=False, weight_mask=mask)
        return self.catalog.iloc[idx[0]].assign(score=np.round(scores[0], 3))

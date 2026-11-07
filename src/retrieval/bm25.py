"""BM25 over the catalog: title, region name, body, notes and table code as one text per row."""

import hashlib
import re
from pathlib import Path

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


def fingerprint(catalog):
    """Changes when a row, its text or the row order changes: a saved index is only valid for the catalog it was built from."""
    texts = (bm25_text(r) for r in catalog.to_dict("records"))
    return hashlib.sha256("\n".join(f"{d}\t{t}" for d, t in zip(catalog["doc_id"], texts)).encode()).hexdigest()


class BM25:
    """`saved`: a folder written by save(), which skips tokenizing and indexing 75k rows at every start."""

    def __init__(self, catalog, saved=None):
        self.catalog = catalog.reset_index(drop=True)
        if saved:
            assert (Path(saved) / "fingerprint.txt").read_text() == fingerprint(self.catalog), f"{saved} was built from another catalog: rebuild it"
            self.model = bm25s.BM25.load(saved, mmap=True, show_progress=False)
        else:
            self.model = bm25s.BM25()
            self.model.index([tokenize(bm25_text(r)) for r in self.catalog.to_dict("records")], show_progress=False)

    def save(self, folder):
        self.model.save(folder, show_progress=False)
        (Path(folder) / "fingerprint.txt").write_text(fingerprint(self.catalog))

    def search(self, question, k=5, domains=None):
        """Top-k catalog rows with a `score` column; `domains` limits scoring to those domain ids."""
        tokens = tokenize(question)
        if not tokens:
            return self.catalog.iloc[0:0].assign(score=[])
        mask = self.catalog["domain"].isin(domains).to_numpy(dtype=float) if domains else None
        idx, scores = self.model.retrieve([tokens], k=k, show_progress=False, weight_mask=mask)
        return self.catalog.iloc[idx[0]].assign(score=np.round(scores[0], 3))

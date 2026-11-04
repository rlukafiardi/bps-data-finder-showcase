import pandas as pd

from src.retrieval import bm25


def catalog():
    filler = " ".join(f"kata{i}" for i in range(150))  # a long summary, as BRS publications have
    rows = [
        ("a", "Berita Resmi Statistik Januari 2025", filler),
        ("b", "Berita Resmi Statistik Juli 2025", ""),
        ("c", "Statistik Pertanian Tanaman Pangan", ""),
    ]
    return pd.DataFrame(
        [{"doc_id": i, "domain": "0000", "title": t, "body": b, "notes": "", "table_code": None} for i, t, b in rows]
    )


def first_hit():
    return bm25.BM25(catalog()).search("berita resmi statistik januari 2025", k=3)["doc_id"].iloc[0]


def test_long_summary_buries_the_title_without_weighting(monkeypatch):
    monkeypatch.setattr(bm25, "TITLE_WEIGHT", 1)
    assert first_hit() == "b"  # length normalisation favours the document without a summary


def test_shipped_title_weight_brings_back_the_exact_match():
    assert first_hit() == "a"

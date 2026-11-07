import pandas as pd
import pytest

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


def test_a_saved_index_answers_like_a_built_one_and_refuses_another_catalog(tmp_path):
    built = bm25.BM25(catalog())
    built.save(tmp_path)
    loaded = bm25.BM25(catalog(), saved=tmp_path)
    question = "berita resmi statistik januari 2025"
    assert loaded.search(question, k=3)["doc_id"].tolist() == built.search(question, k=3)["doc_id"].tolist()
    changed = catalog().assign(title=lambda d: d["title"].str.replace("Juli", "Agustus"))
    with pytest.raises(AssertionError, match="another catalog"):
        bm25.BM25(changed, saved=tmp_path)

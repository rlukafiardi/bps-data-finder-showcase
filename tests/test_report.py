import pandas as pd

from evals import report


def run(hits, method, n=40):
    rank = [1 if i < hits else None for i in range(n)]
    return pd.DataFrame({
        "question": [f"q{i}" if i < n - 1 else "<script>alert(1)</script>" for i in range(n)],
        "source": ["claude"] * n, "type": ["var"] * n, "rank": rank, "top1": ["var:0000 something"] * n,
        "recall@5": [r is not None for r in rank], "mrr": [1.0 if r else 0.0 for r in rank], "method": method,
    })


def test_report_reads_the_steps_and_escapes_questions(tmp_path, monkeypatch):
    results = pd.concat([run(20, "bm25"), run(22, "bm25+region"), run(38, "hybrid+region"), run(37, "rewrite+hybrid+region"), run(36, "rewrite+bm25+region")])
    results.to_parquet(tmp_path / "results.parquet")
    (tmp_path / "history.csv").write_text(
        "date,source,catalog_rows,n,method,recall5,recall5_lo,recall5_hi,mrr\n"
        "2026-11-03,backfill:baseline.txt,,70,bps-search-keywords,0.186,,,0.153\n"
        "2026-11-04,abc123,74938,40,rewrite+hybrid+region,0.925,0.8,1.0,0.9\n")
    monkeypatch.setattr(report, "RESULTS", tmp_path / "results.parquet")
    monkeypatch.setattr(report, "HISTORY", tmp_path / "history.csv")
    page = report.build()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    rows = {r.split("</td>")[0].split(">")[-1]: r for r in page.split("<tr>") if "Change in" not in r}
    assert "within noise" in rows["Region ranking on BM25"]  # 2 questions of 40
    assert "clearly better" in rows["Hybrid (BM25 + embeddings) instead of BM25 alone"]  # 16 questions of 40
    assert "within noise" in rows["Gemini query rewrite on top of hybrid"]  # 1 question lost
    assert "within noise" in rows["Embeddings added to the rewrite + BM25 pipeline (what the model files cost us)"]  # 1 question of 40
    assert "not kept" in page and "<svg" in page

"""Dense retrieval with a multilingual embedding model, plus BM25 + dense fusion (RRF).

Embeddings are cached in data/processed/ per model, keyed by doc_id and text, so a rebuilt
catalog only embeds new or changed rows.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

from src.config import EMBED_MODEL
from src.retrieval.bm25 import doc_text, fingerprint

CACHE = Path("data/processed") / f"embeddings_{EMBED_MODEL.replace('/', '__')}.parquet"
RRF_K = 60


class Dense:
    """`saved`: a folder written by save(); it skips reading the 126 MB embedding cache and matching 75k rows against it at every start."""

    def __init__(self, catalog, saved=None):
        self.catalog = catalog.reset_index(drop=True)
        self.model = SentenceTransformer(EMBED_MODEL)
        if saved:
            assert (Path(saved) / "fingerprint.txt").read_text() == fingerprint(self.catalog), f"{saved} was built from another catalog: rebuild it"
            self.vectors = np.load(Path(saved) / "vectors.npy", mmap_mode="r")
        else:
            texts = [doc_text(r) for r in self.catalog.to_dict("records")]
            self.vectors = self._embed_cached(self.catalog["doc_id"].tolist(), texts)

    def save(self, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)
        np.save(Path(folder) / "vectors.npy", self.vectors)
        (Path(folder) / "fingerprint.txt").write_text(fingerprint(self.catalog))

    def _embed_cached(self, doc_ids, texts):
        cached = pd.read_parquet(CACHE) if CACHE.exists() else pd.DataFrame(columns=["doc_id", "text", "vector"])
        known = {(d, t): v for d, t, v in zip(cached["doc_id"], cached["text"], cached["vector"])}
        todo = [i for i, key in enumerate(zip(doc_ids, texts)) if key not in known]
        if todo:
            new = self.model.encode(
                [f"passage: {texts[i]}" for i in todo], batch_size=64, normalize_embeddings=True, show_progress_bar=True
            )
            for i, v in zip(todo, new):
                known[(doc_ids[i], texts[i])] = v
            pd.DataFrame(
                [{"doc_id": d, "text": t, "vector": np.asarray(v, dtype=np.float32)} for (d, t), v in known.items()]
            ).to_parquet(CACHE, index=False)
        return np.stack([known[key] for key in zip(doc_ids, texts)]).astype(np.float32)

    def search(self, question, k=5, domains=None):
        q = self.model.encode(f"query: {question}", normalize_embeddings=True)
        scores = self.vectors @ q
        if domains:
            scores = np.where(self.catalog["domain"].isin(domains).to_numpy(), scores, -np.inf)
        top = np.argsort(-scores)[:k]
        return self.catalog.iloc[top].assign(score=np.round(scores[top], 4))


class Hybrid:
    """Reciprocal rank fusion of several retrievers."""

    def __init__(self, *retrievers, depth=300):
        self.retrievers = retrievers
        self.depth = depth

    def search(self, question, k=5, domains=None):
        fused = {}
        rows = {}
        for retriever in self.retrievers:
            hits = retriever.search(question, k=self.depth, domains=domains)
            for rank, (doc_id, row) in enumerate(zip(hits["doc_id"], hits.to_dict("records")), start=1):
                fused[doc_id] = fused.get(doc_id, 0) + 1 / (RRF_K + rank)
                rows.setdefault(doc_id, row)
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        return pd.DataFrame([rows[d] for d in top]).assign(score=[round(fused[d], 5) for d in top])

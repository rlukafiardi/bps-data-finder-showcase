"""Write the search indexes the API loads at start: BM25 and the embedding matrix, for the current catalog.

    uv run python -m src.retrieval.save_index
"""

import pandas as pd

from src.retrieval.bm25 import BM25
from src.retrieval.dense import Dense

CATALOG = "data/processed/catalog.parquet"
FOLDER = "data/processed/serving"

if __name__ == "__main__":
    catalog = pd.read_parquet(CATALOG)
    BM25(catalog).save(f"{FOLDER}/bm25")
    Dense(catalog).save(f"{FOLDER}/dense")
    print(f"saved the indexes of {len(catalog)} rows in {FOLDER}")

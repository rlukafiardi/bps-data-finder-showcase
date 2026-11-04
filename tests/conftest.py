from pathlib import Path

from src.retrieval import regions

# the region lists (BPS's own, public) ship with the tests, so they pass on a checkout without the pulled data
regions.RAW = Path(__file__).parent / "fixtures" / "catalog"

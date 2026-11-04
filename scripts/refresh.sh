#!/usr/bin/env bash
# Refresh the catalog from BPS, rebuild it, embed the new rows, run the eval as a smoke test and rebuild docs/eval-report.html.
# A failed check puts the previous catalog back.
#
#   scripts/refresh.sh            current-year publications and press releases (~5 min)
#   scripts/refresh.sh all        every page again (hours; rerun the same command to resume)
#
# Uploading the catalog and embeddings to the bucket, and exporting the search/feedback log events,
# come with the deploy.
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:-recent}"
[[ "$mode" == recent || "$mode" == all ]] || { echo "usage: scripts/refresh.sh [recent|all]" >&2; exit 2; }
catalog=data/processed/catalog.parquet
previous=data/processed/catalog.previous.parquet

uv run python -m src.ingestion.pull_catalog --refresh "$mode"
cp "$catalog" "$previous"
uv run python -m src.ingestion.build_catalog
uv run python - <<'PY'
import pandas as pd
old, new = (pd.read_parquet(f"data/processed/catalog{s}.parquet") for s in (".previous", ""))
added = new[~new["doc_id"].isin(old["doc_id"])]
removed = old[~old["doc_id"].isin(new["doc_id"])]
print(f"\ncatalog rows: {len(old)} -> {len(new)} (added {len(added)}, removed {len(removed)})")
print("added by type:", added["type"].value_counts().to_dict())
PY
if ! uv run python -m evals.run_eval --smoke > data/processed/eval_refresh.txt 2>&1; then
  tail -3 data/processed/eval_refresh.txt
  cp "$previous" "$catalog"
  echo "Smoke check failed: the previous catalog is back. Full report: data/processed/eval_refresh.txt" >&2
  exit 1
fi
tail -1 data/processed/eval_refresh.txt
uv run python -m evals.report

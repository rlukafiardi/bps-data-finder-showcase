# Search + values API. Build context: pyproject.toml, uv.lock, src/, app/ (see .gcloudignore). The catalog and the
# embeddings are not in the image: a private bucket is mounted read-only at /app/data (scripts/publish_data.sh fills it).
FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_NO_CACHE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app HF_HOME=/app/hf PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
# torch from PyPI on Linux pulls about 3 GB of NVIDIA libraries: install the locked torch version from the CPU index
# first, so sentence-transformers finds torch installed, then the other locked packages without the NVIDIA ones
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/req.txt \
 && TORCH=$(grep -E '^torch==' /tmp/req.txt | head -1 | cut -d';' -f1 | tr -d ' ') \
 && grep -v -E '^(torch==|nvidia-|triton|cuda-)' /tmp/req.txt > /tmp/req-cpu.txt \
 && uv venv .venv \
 && uv pip install --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu "$TORCH" \
 && uv pip install --python .venv/bin/python -r /tmp/req-cpu.txt \
 && ! uv pip list --python .venv/bin/python | grep -i -E '^(nvidia-|triton)'  # fail the build if any came back
COPY src ./src
COPY app ./app
# the embedding model goes into the image (only the files it loads), so a cold start does not download it
RUN python -c "from huggingface_hub import snapshot_download; from src.config import EMBED_MODEL; snapshot_download(EMBED_MODEL, allow_patterns=['*.json', 'model.safetensors', 'sentencepiece.bpe.model', '1_Pooling/*'])"
ENV HF_HUB_OFFLINE=1
RUN useradd --system --no-create-home api
USER api
# one process: the BPS spacing is kept in memory, so a second instance would break the 20 requests a minute budget
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --limit-concurrency 20 --no-server-header"]

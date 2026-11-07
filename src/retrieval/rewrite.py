"""LLM query rewrite: turn a user question into a BPS-style Indonesian search query.

Results are cached in data/processed/rewrite_cache.jsonl per (model, prompt, question), so a rerun of
the eval only calls the API for new questions or a changed prompt.
"""

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx2
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from src.config import REWRITE_MODEL, REWRITE_SPACING_S

CACHE = Path("data/processed/rewrite_cache.jsonl")
RATE_LIMIT_WAIT_S = 65
RETRIES = 3
SERVING_TIMEOUT_MS = 10000  # Gemini rejects deadlines under 10 s
# after a failure the API skips Gemini for a while: on 2026-11-04 the free tier answered 503/504 for most calls on every
# Flash model, and each failed attempt added up to 10 s to a visitor's search
COOLDOWN_S = 120
# a 503 is often over in seconds (2026-11-05: about half of the calls failed at once, the next one worked), so a server
# error is retried once and then skips Gemini for a short time; a 429 or a timeout keeps the long cooldown
SERVER_ERROR_COOLDOWN_S = 30

PROMPT = """You rewrite questions about Indonesian official statistics (BPS) into a search query that matches
how BPS titles its tables, publications and press releases.

Rules:
- Write the query in Indonesian, using BPS terminology. Translate English questions.
- Expand acronyms and add the full BPS term (TPT -> Tingkat Pengangguran Terbuka, IPM -> Indeks
  Pembangunan Manusia, P0 -> Persentase Penduduk Miskin, P1 -> Indeks Kedalaman Kemiskinan,
  P2 -> Indeks Keparahan Kemiskinan, NTP -> Nilai Tukar Petani,
  PDRB ADHB/ADHK -> Produk Domestik Regional Bruto Atas Dasar Harga Berlaku/Konstan, BPJS -> Jaminan
  Kesehatan, PMDN/PMA -> Penanaman Modal Dalam Negeri/Asing, wisman -> wisatawan mancanegara).
- Keep the breakdown the user asks for in BPS words ("per kabupaten" -> "menurut Kabupaten/Kota",
  "tiap provinsi" -> "menurut Provinsi"). Add no breakdown the user did not ask for.
- Keep the period exactly as asked (month name, quarter as "Triwulan I", year).
- When a specific item belongs to a BPS group, add the group name too (cabai, bawang merah -> tanaman
  sayuran; kopi, karet -> tanaman perkebunan; sapi, kambing -> ternak; truk, bus -> kendaraan bermotor).
- Add one or two synonyms BPS uses in titles when the user's word is informal (sembako -> harga eceran
  bahan pokok; gaji -> upah/gaji; pakai internet -> mengakses internet).
- Do not add facts, numbers or regions the user did not ask for.
- region: the region asked about, written as BPS names it ("Sumatera Selatan", "Kota Bandung",
  "Kabupaten Bogor", "Kepulauan Riau"); "Indonesia" if the user asks for national or all provinces;
  null if no region is named."""

SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "region": {"type": ["string", "null"]},
    },
    "required": ["query", "region"],
}


class RewriteUnavailable(Exception):
    pass


class Rewriter:
    """serving=True (the API): never wait. A call inside the spacing window or the cooldown after a failure
    raises RewriteUnavailable at once; a 429, a server error or a timeout raises it and starts the cooldown (a server error is retried once first).
    The cache stays in memory (the data folder is read-only there). serving=False (the eval): wait out
    limits and append to the cache file."""

    def __init__(self, model=REWRITE_MODEL, serving=False):
        load_dotenv(".env")
        self.model = model
        self.serving = serving
        http_options = types.HttpOptions(timeout=SERVING_TIMEOUT_MS) if serving else None
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=http_options)
        self.lock = threading.Lock()
        self.cache = {}
        if CACHE.exists():
            for line in CACHE.read_text().splitlines():
                row = json.loads(line)
                self.cache[row["key"]] = row["result"]
        self.last_call = 0.0
        self.down_until = 0.0

    def _key(self, question):
        return hashlib.sha256(f"{self.model}\n{PROMPT}\n{question}".encode()).hexdigest()

    def rewrite(self, question):
        """{"query": str, "region": str | None}"""
        key = self._key(question)
        if key not in self.cache:
            result = self._call_serving(question) if self.serving else self._call(question)
            self.cache[key] = result
            if not self.serving:
                with CACHE.open("a") as f:
                    f.write(json.dumps({"key": key, "model": self.model, "question": question, "result": result}) + "\n")
        return self.cache[key]

    def rewrite_or_none(self, question):
        try:
            return self.rewrite(question)
        except RewriteUnavailable:
            return None

    def _config(self):
        return types.GenerateContentConfig(
            system_instruction=PROMPT, response_mime_type="application/json", response_json_schema=SCHEMA
        )

    def _call_serving(self, question):
        with self.lock:
            now = time.monotonic()
            if now < self.last_call + REWRITE_SPACING_S or now < self.down_until:
                raise RewriteUnavailable("inside the spacing window or the cooldown")
            self.last_call = now
        for attempt in range(2):
            try:
                response = self.client.models.generate_content(model=self.model, contents=question, config=self._config())
                break
            except errors.ClientError as e:
                if e.code != 429:
                    raise
                self.down_until = time.monotonic() + COOLDOWN_S
                raise RewriteUnavailable("rate limited") from e
            except errors.ServerError as e:
                if attempt == 0:
                    continue
                self.down_until = time.monotonic() + SERVER_ERROR_COOLDOWN_S
                raise RewriteUnavailable("ServerError") from e
            except httpx2.TimeoutException as e:
                self.down_until = time.monotonic() + COOLDOWN_S
                raise RewriteUnavailable("TimeoutException") from e
        return json.loads(response.text)

    def _call(self, question):
        config = self._config()
        for attempt in range(RETRIES):
            time.sleep(max(0.0, self.last_call + REWRITE_SPACING_S - time.monotonic()))
            self.last_call = time.monotonic()
            try:
                response = self.client.models.generate_content(model=self.model, contents=question, config=config)
                return json.loads(response.text)
            except errors.ClientError as e:
                if e.code != 429:
                    raise
                time.sleep(RATE_LIMIT_WAIT_S)
            except errors.ServerError:
                time.sleep(REWRITE_SPACING_S * 2 ** (attempt + 1))
        raise RuntimeError(f"rewrite still failing after {RETRIES} tries: {question!r}")


class Rewritten:
    """Search with the question plus its rewrite, so the original words still count."""

    def __init__(self, retriever, rewriter):
        self.retriever = retriever
        self.rewriter = rewriter

    def search(self, question, k=5):
        r = self.rewriter.rewrite(question)
        return self.retriever.search(" ".join(p for p in (question, r["query"], r["region"]) if p), k=k)

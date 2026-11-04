"""BPS WebAPI client for live value lookups.

BPS answers 429 above ~20 requests a minute for the whole key, so every request takes a slot 3 s after
the previous one, for all visitors together; a visitor whose slot is more than MAX_WAIT_S away gets
Busy instead of waiting. Answers are cached for a day and returned with the time they were fetched,
so the page can say how fresh a number is.
"""

import os
import threading
import time

import httpx
from dotenv import load_dotenv

load_dotenv(".env")
BASE = "https://webapi.bps.go.id/v1"
SLOT_S = 3.0
MAX_WAIT_S = 15.0
TTL_S = 24 * 3600
CACHE_SIZE = 200


class Busy(Exception):
    pass


class BpsError(Exception):
    pass


lock = threading.Lock()
next_slot = 0.0
cache = {}  # (path, params) -> (fetched_at, body), oldest first


def get(path, params=None):
    """(body, fetched_at as epoch seconds). `path` contains {key}."""
    global next_slot
    cache_key = (path, tuple(sorted((params or {}).items())))
    hit = cache.get(cache_key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1], hit[0]
    with lock:
        now = time.monotonic()
        slot = max(now, next_slot)
        if slot - now > MAX_WAIT_S:
            raise Busy
        next_slot = slot + SLOT_S
    time.sleep(slot - now)
    try:
        resp = httpx.get(BASE + path.format(key=os.environ["BPS_API_KEY"]), params=params, timeout=30)
    except httpx.HTTPError as e:
        raise BpsError(type(e).__name__) from None  # the error text holds the URL, which holds the key
    if resp.status_code != 200:
        raise BpsError(f"HTTP {resp.status_code}")
    fetched_at = time.time()
    cache[cache_key] = (fetched_at, resp.json())
    while len(cache) > CACHE_SIZE:
        del cache[next(iter(cache))]
    return cache[cache_key][1], fetched_at

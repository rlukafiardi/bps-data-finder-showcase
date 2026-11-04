import json
import os
import time

import httpx
import pytest

os.environ.setdefault("BPS_API_KEY", "test-key")
from src.ingestion import pull_catalog  # noqa: E402


@pytest.fixture(autouse=True)
def request_log(tmp_path, monkeypatch):
    monkeypatch.setattr(pull_catalog, "LOG", tmp_path / "requests.log")


def client(calls):
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": "fresh"})

    return httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(handler))


def test_refresh_fetches_pages_older_than_the_cutoff_and_keeps_newer_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(pull_catalog, "DELAY_S", 0)
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    for page in (old, new):
        page.write_text(json.dumps({"data": "cached"}))
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    calls = []
    with client(calls) as c:
        monkeypatch.setattr(pull_catalog, "cutoff", time.time() - 60)
        assert pull_catalog.get(c, "/a", {}, old) == {"data": "fresh"}
        assert pull_catalog.get(c, "/b", {}, new) == {"data": "cached"}
        assert len(calls) == 1
        assert json.loads(old.read_text()) == {"data": "fresh"} and not list(tmp_path.glob("*.tmp"))
        monkeypatch.setattr(pull_catalog, "cutoff", None)  # a normal pull never refetches
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        assert pull_catalog.get(c, "/a", {}, old) == {"data": "fresh"} and len(calls) == 1


def test_a_failed_refresh_keeps_the_old_page(tmp_path, monkeypatch):
    monkeypatch.setattr(pull_catalog, "DELAY_S", 0)
    monkeypatch.setattr(pull_catalog, "cutoff", time.time() + 60)
    page = tmp_path / "p.json"
    page.write_text(json.dumps({"data": "cached"}))
    c = httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    try:
        pull_catalog.get(c, "/a", {}, page)
    except pull_catalog.Stop:
        pass
    else:
        raise AssertionError("a 403 must stop the pull")
    assert json.loads(page.read_text()) == {"data": "cached"}

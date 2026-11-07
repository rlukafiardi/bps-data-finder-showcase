import os

import pytest
from google.genai import errors

os.environ.setdefault("GEMINI_API_KEY", "test-key")
from src.retrieval import rewrite  # noqa: E402


def test_a_failed_call_skips_gemini_until_the_cooldown_ends(monkeypatch):
    r = rewrite.Rewriter(serving=True)
    r.cache = {}
    calls = []

    def overloaded(**kw):
        calls.append(kw["contents"])
        raise errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})

    monkeypatch.setattr(r.client.models, "generate_content", overloaded)
    with pytest.raises(rewrite.RewriteUnavailable):
        r.rewrite("inflasi riau")
    r.last_call = -1e9  # past the spacing window: only the cooldown can stop the next call
    assert r.rewrite_or_none("ipm sleman") is None
    assert calls == ["inflasi riau"] * 2, "one retry, then no call during the cooldown"
    r.last_call, r.down_until = -1e9, 0.0
    assert r.rewrite_or_none("ipm sleman") is None
    assert calls == ["inflasi riau"] * 2 + ["ipm sleman"] * 2, "Gemini is tried again after the cooldown"


def test_a_server_error_is_retried_once(monkeypatch):
    r = rewrite.Rewriter(serving=True)
    r.cache = {}
    calls = []

    class Ok:
        text = '{"query": "inflasi", "region": null}'

    def flaky(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        return Ok()

    monkeypatch.setattr(r.client.models, "generate_content", flaky)
    assert r.rewrite("inflasi riau")["query"] == "inflasi"
    assert len(calls) == 2 and r.down_until == 0.0

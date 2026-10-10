from datetime import datetime, timedelta, timezone
import pytest
from app.search import *


def sample_response(ts):
    q = PlannedQuery(query='"ADV/01/2026"', purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=10)
    return SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK, captured_at=ts,
                          search_id="abc", results=(OrganicResult(position=1, title="x", link="https://example.gov/x"),),
                          response_sha256="deadbeef")


def test_request_key_includes_localization_and_is_stable():
    a = request_key("google", " q ", {"hl": "en", "gl": "in"})
    b = request_key("google", "q", {"gl": "in", "hl": "en"})
    c = request_key("google", "q", {"gl": "us", "hl": "en"})
    assert a == b
    assert a != c


def test_live_cache_respects_ttl(tmp_path):
    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    cache = LiveSearchCache(tmp_path / "live", ttl=timedelta(minutes=20))
    cache.put("k", sample_response(now))
    assert cache.get("k", now + timedelta(minutes=19)) is not None
    assert cache.get("k", now + timedelta(minutes=21)) is None
    assert cache.get("missing", now) is None


def test_replay_store_is_immutable(tmp_path):
    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    store = ReplayEvidenceStore(tmp_path / "replay")
    store.put_once("k", sample_response(now))
    got = store.get("k")
    assert got is not None and got.search_id == "abc"
    with pytest.raises(FileExistsError):
        store.put_once("k", sample_response(now))
    assert store.get("missing") is None

from datetime import datetime, timezone
from app.search import *


def test_manifest_contains_no_api_key_field():
    q = PlannedQuery(query="q", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                       captured_at=datetime.now(timezone.utc), search_id="id",
                       results=(OrganicResult(link="https://example.com"),), response_sha256="h")
    m = to_manifest_entry(r)
    data = m.model_dump()
    assert "api_key" not in data
    assert data["result_count"] == 1


def test_manifest_preserves_controlled_provider_error_code_without_diagnostics():
    q = PlannedQuery(query="q", purpose=QueryPurpose.AMENDMENT, tier=QueryTier.CORE, priority=1)
    response = SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.ERROR,
                              captured_at=datetime.now(timezone.utc), error_code="HTTP_429",
                              error_message="SerpApi HTTP error")
    entry = to_manifest_entry(response)
    serialized = entry.model_dump_json()
    assert entry.error_code == "HTTP_429"
    assert "SerpApi HTTP error" not in serialized
    assert "api_key" not in serialized


def test_manifest_preserves_sanitized_attempt_timing_only():
    q = PlannedQuery(query="q", purpose=QueryPurpose.EXTENSION, tier=QueryTier.CORE, priority=1)
    response = SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.ERROR,
                              captured_at=datetime.now(timezone.utc), error_code="TIMEOUT",
                              elapsed_ms=15000, timeout_kind="TOTAL_ATTEMPT_DEADLINE")
    entry = to_manifest_entry(response)
    assert entry.elapsed_ms == 15000
    assert entry.timeout_kind == "TOTAL_ATTEMPT_DEADLINE"

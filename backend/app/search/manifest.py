from .models import SearchManifestEntry, SearchResponse


def to_manifest_entry(response: SearchResponse) -> SearchManifestEntry:
    return SearchManifestEntry(
        query=response.query.query,
        purpose=response.query.purpose,
        tier=response.query.tier,
        mode=response.mode,
        status=response.status,
        captured_at=response.captured_at,
        search_id=response.search_id,
        response_sha256=response.response_sha256,
        result_count=len(response.results),
        provider_cached=response.provider_cached,
        provider_status=response.provider_status,
        error_code=response.error_code,
        elapsed_ms=response.elapsed_ms,
        timeout_kind=response.timeout_kind,
        request_parameters=response.request_parameters,
    )

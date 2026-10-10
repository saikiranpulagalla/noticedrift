from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re
import time
import asyncio
import httpx
from .models import PlannedQuery, SearchMode, SearchResponse, SearchStatus, OrganicResult
from .sanitize import sanitize_for_persistence

SERPAPI_URL = "https://serpapi.com/search.json"
MAX_PROVIDER_BYTES = 2 * 1024 * 1024
DEFAULT_ATTEMPT_TIMEOUT_SECONDS = 15.0

def parse_provider_payload(payload: object, planned: PlannedQuery, *, captured: datetime,
                           request_parameters: tuple[tuple[str, str], ...] = (),
                           mode: SearchMode = SearchMode.LIVE) -> SearchResponse:
    """Single validated adapter shared by live and raw replay. Never persists upstream errors."""
    defaults = dict(query=planned, mode=mode, captured_at=captured, request_parameters=request_parameters)
    if not isinstance(payload, dict):
        return SearchResponse(**defaults, status=SearchStatus.ERROR, error_code="INVALID_SCHEMA",
                              error_message="Unexpected SerpApi response structure")
    metadata = payload.get("search_metadata", {})
    if not isinstance(metadata, dict):
        return SearchResponse(**defaults, status=SearchStatus.ERROR, error_code="INVALID_SCHEMA")
    # `Success` without an organic-results key is not proof of an empty
    # search. SerpApi can legitimately return no organic results; absent
    # field support needs a documented provider state, not optimistic coverage.
    organic_field_present = "organic_results" in payload
    organic = payload.get("organic_results", [])
    if not isinstance(organic, list) or any(not isinstance(x, dict) for x in organic):
        return SearchResponse(**defaults, status=SearchStatus.ERROR, error_code="INVALID_SCHEMA")
    provider_status = metadata.get("status")
    if not isinstance(provider_status, str):
        provider_status = None
    provider_cached = None if provider_status is None else provider_status.casefold() == "cached"
    metadata_fields = dict(search_id=metadata.get("id") if isinstance(metadata.get("id"), str) else None,
                           provider_status=provider_status, provider_cached=provider_cached)
    status_normalized = provider_status.casefold() if provider_status else None
    search_parameters = payload.get("search_parameters")
    if search_parameters is not None:
        if not isinstance(search_parameters, dict):
            return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                                  error_code="INVALID_QUERY_PROVENANCE")
        echoed = search_parameters.get("q")
        if echoed is not None:
            if not isinstance(echoed, str) or re.sub(r"\s+", " ", echoed).strip() != re.sub(r"\s+", " ", planned.query).strip():
                return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                                      error_code="EXECUTED_QUERY_MISMATCH")
    if status_normalized in {"error", "processing", "queued"}:
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code=("PROVIDER_" + status_normalized.upper()),
                              error_message="SerpApi search did not complete successfully")
    if provider_status is not None and status_normalized not in {"success", "cached"}:
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code="UNKNOWN_PROVIDER_STATE")
    empty_notice = (len(organic) == 0 and isinstance(payload.get("error"), str)
                    and "hasn't returned any results" in payload["error"].casefold())
    if payload.get("error") and not (status_normalized == "success" and empty_notice):
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code="SERPAPI_ERROR", error_message="SerpApi rejected the search")
    if not organic_field_present and not empty_notice:
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code="MISSING_ORGANIC_RESULT_STATE")
    sanitized = sanitize_for_persistence(payload)
    raw = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > MAX_PROVIDER_BYTES:
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code='PROVIDER_BODY_TOO_LARGE')
    digest = hashlib.sha256(raw).hexdigest()
    # Bounded adapter must disclose truncation. Dropped discoveries can never
    # support an assertion that no newer governing document exists.
    if len(organic) > 100:
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code="PROVIDER_RESULT_TRUNCATED", response_sha256=digest)
    parsed = []
    rejected = 0
    for item in organic:
        link = item.get("link")
        if not isinstance(link, str) or not link:
            rejected += 1
            continue
        try:
            parsed.append(OrganicResult(position=item.get("position") if isinstance(item.get("position"), int) else None,
                                        title=item.get("title") if isinstance(item.get("title"), str) else None,
                                        link=link,
                                        snippet=item.get("snippet") if isinstance(item.get("snippet"), str) else None,
                                        displayed_link=item.get("displayed_link") if isinstance(item.get("displayed_link"), str) else None))
        except ValueError:
            rejected += 1  # unsafe URL is never forwarded to browser/fetcher
    if rejected:
        # Never interpret silently dropped discoveries as complete coverage.
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code="PROVIDER_RESULTS_REJECTED", response_sha256=digest)
    if organic and not parsed:
        return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.ERROR,
                              error_code="ALL_RESULT_URLS_REJECTED")
    return SearchResponse(**defaults, **metadata_fields, status=SearchStatus.OK,
                          results=tuple(parsed), response_sha256=digest)

class SerpApiClient:
    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None,
                 timeout_seconds: float = DEFAULT_ATTEMPT_TIMEOUT_SECONDS):
        if not api_key:
            raise ValueError("SERPAPI_API_KEY is required for live search")
        if not isinstance(timeout_seconds, (int, float)) or not 1.0 <= timeout_seconds <= 60.0:
            raise ValueError("INVALID_PROVIDER_ATTEMPT_TIMEOUT")
        self._api_key = api_key
        self._owned_client = client is None
        self.timeout_seconds = float(timeout_seconds)
        self._client = client or httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False)

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def search(self, planned: PlannedQuery, *, gl: str = "in", hl: str = "en",
                     no_cache: bool = True, location: str | None = None) -> SearchResponse:
        captured = datetime.now(timezone.utc)
        started = time.monotonic()
        params = {"engine": "google", "q": planned.query, "api_key": self._api_key,
                  "gl": gl, "hl": hl, "no_cache": str(no_cache).lower()}
        if location:
            params["location"] = location
        # No raw request URL with API key may enter metadata or logs.
        executed = tuple(sorted((k, str(v)) for k, v in params.items() if k != "api_key"))
        defaults = dict(query=planned, mode=SearchMode.LIVE, captured_at=captured, request_parameters=executed)

        def measured(response: SearchResponse, *, timeout_kind: str | None = None) -> SearchResponse:
            return response.model_copy(update={
                "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
                "timeout_kind": timeout_kind,
            })

        try:
            # Streaming bound applies before JSON decoding, including servers
            # with absent/misleading Content-Length or chunked transfer.
            # httpx's timeout applies to individual I/O operations. This outer
            # deadline also bounds a trickle response that stays below every
            # per-read timeout, with no retry or extra credit reservation.
            async with asyncio.timeout(self.timeout_seconds):
                async with self._client.stream("GET", SERPAPI_URL, params=params) as response:
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    if length is not None:
                        try:
                            if int(length) > MAX_PROVIDER_BYTES:
                                return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                                               error_code="PROVIDER_BODY_TOO_LARGE"))
                        except ValueError:
                            return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                                           error_code="INVALID_PROVIDER_CONTENT_LENGTH"))
                    chunks = []
                    count = 0
                    async for chunk in response.aiter_bytes():
                        count += len(chunk)
                        if count > MAX_PROVIDER_BYTES:
                            return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                                           error_code="PROVIDER_BODY_TOO_LARGE"))
                        chunks.append(chunk)
            payload = json.loads(b"".join(chunks))
        except TimeoutError:
            return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                           error_code="TIMEOUT"), timeout_kind="TOTAL_ATTEMPT_DEADLINE")
        except httpx.TimeoutException:
            return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                           error_code="TIMEOUT", error_message="SerpApi request timed out"),
                            timeout_kind="HTTPX_TIMEOUT")
        except httpx.HTTPStatusError as exc:
            return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                           error_code=f"HTTP_{exc.response.status_code}", error_message="SerpApi HTTP error"))
        except (json.JSONDecodeError, ValueError):
            return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                           error_code="INVALID_JSON", error_message="Invalid JSON"))
        except httpx.HTTPError:
            return measured(SearchResponse(**defaults, status=SearchStatus.ERROR,
                                           error_code="NETWORK_ERROR", error_message="SerpApi request failed"))
        return measured(parse_provider_payload(payload, planned, captured=captured, request_parameters=executed))

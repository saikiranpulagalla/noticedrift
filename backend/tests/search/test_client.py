import json
import asyncio
import httpx
import pytest
from app.search import *


def query():
    return PlannedQuery(query='"ADV/01/2026"', purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=10)


@pytest.mark.asyncio
async def test_live_client_parses_success_without_leaking_key():
    seen = {}
    async def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={
            "search_metadata": {"id": "sid"},
            "organic_results": [
                {"position": 1, "title": "Official", "link": "https://example.gov/n", "snippet": "hello"},
                {"position": 2, "title": "No link"},
            ],
        })
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    api = SerpApiClient("SECRET", client=client)
    result = await api.search(query())
    assert result.status == SearchStatus.ERROR
    assert result.error_code == 'PROVIDER_RESULTS_REJECTED'
    assert result.search_id == "sid"
    assert len(result.results) == 0
    assert result.response_sha256
    # Transport must receive the key, but the returned serializable result must not retain it.
    assert "api_key=SECRET" in seen["url"]
    assert "SECRET" not in result.model_dump_json()
    await client.aclose()


@pytest.mark.asyncio
async def test_serpapi_error_payload_is_structured():
    async def handler(request):
        return httpx.Response(200, json={"search_metadata": {"id": "sid"}, "error": "bad request"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await SerpApiClient("x", client=client).search(query())
    assert result.status == SearchStatus.ERROR
    assert result.error_code == "SERPAPI_ERROR"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_error_is_structured():
    async def handler(request):
        return httpx.Response(429, json={"error": "rate"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await SerpApiClient("x", client=client).search(query())
    assert result.status == SearchStatus.ERROR
    assert result.error_code == "HTTP_429"
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_json_is_structured():
    async def handler(request):
        return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await SerpApiClient("x", client=client).search(query())
    assert result.status == SearchStatus.ERROR
    assert result.error_code == "INVALID_JSON"
    await client.aclose()


@pytest.mark.asyncio
async def test_network_error_is_structured():
    async def handler(request):
        raise httpx.ConnectError("boom", request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await SerpApiClient("x", client=client).search(query())
    assert result.status == SearchStatus.ERROR
    assert result.error_code == "NETWORK_ERROR"
    await client.aclose()


@pytest.mark.asyncio
async def test_timeout_is_structured():
    async def handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await SerpApiClient("x", client=client).search(query())
    assert result.status == SearchStatus.ERROR
    assert result.error_code == "TIMEOUT"
    assert result.elapsed_ms is not None
    assert result.timeout_kind == "HTTPX_TIMEOUT"
    await client.aclose()


@pytest.mark.asyncio
async def test_total_attempt_deadline_bounds_a_trickle_response_without_retry():
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{'
            await asyncio.sleep(.02)
            yield b'}'
        async def aclose(self):
            pass

    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=SlowStream())))
    api = SerpApiClient("test-only", client=client)
    api.timeout_seconds = .01  # Test-only deadline; constructor enforces live bounds.
    result = await api.search(query())
    assert result.status == SearchStatus.ERROR
    assert result.error_code == "TIMEOUT"
    assert result.timeout_kind == "TOTAL_ATTEMPT_DEADLINE"
    assert result.elapsed_ms is not None and result.elapsed_ms < 1000
    await client.aclose()


@pytest.mark.asyncio
async def test_cancelling_an_attempt_propagates_and_client_closes_cleanly():
    started = asyncio.Event()

    class BlockingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b'{}'
        async def aclose(self):
            pass

    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=BlockingStream())))
    api = SerpApiClient("test-only", client=client)
    task = asyncio.create_task(api.search(query()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client.aclose()
    assert client.is_closed


def test_live_client_requires_api_key():
    with pytest.raises(ValueError):
        SerpApiClient("")


def test_live_client_rejects_unbounded_attempt_timeout():
    with pytest.raises(ValueError, match="INVALID_PROVIDER_ATTEMPT_TIMEOUT"):
        SerpApiClient("test-only", timeout_seconds=61)

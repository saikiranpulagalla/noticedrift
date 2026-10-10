"""Tests for newly added provider protocol/byte limits and durable evidence caps."""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import httpx
import pytest
from app.search.client import parse_provider_payload, SerpApiClient, MAX_PROVIDER_BYTES
from app.search.models import SearchStatus, PlannedQuery, QueryPurpose, QueryTier
from app.sources.store import SnapshotStore
from app.sources.models import SourceSnapshot, SourceFailure
from app.sources.evidence import IssuerAuthorityRegistry, AuthorityAttestation

Q = PlannedQuery(query='"A/2026"',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=10)
T = datetime.now(timezone.utc)

def response(payload):
    return parse_provider_payload(payload,Q,captured=T)

@pytest.mark.parametrize('value', [[], 'invalid', 7])
def test_bad_search_parameters_schema_is_rejected(value):
    r=response({'search_metadata':{'status':'Success'},'search_parameters':value,'organic_results':[]})
    assert r.status==SearchStatus.ERROR and r.error_code=='INVALID_QUERY_PROVENANCE'

@pytest.mark.parametrize('echo', [None, 8, 'other', '"B/2026"'])
def test_invalid_query_echo_is_never_counted(echo):
    payload={'search_metadata':{'status':'Success'},'search_parameters':{'q':echo},'organic_results':[]}
    r=response(payload)
    if echo is None: # missing optional echo is not an affirmative conflict
        assert r.status == SearchStatus.OK
    else:
        assert r.status == SearchStatus.ERROR and r.error_code=='EXECUTED_QUERY_MISMATCH'

def test_provider_whitespace_only_normalization_is_accepted():
    r=response({'search_metadata':{'status':'Success'},'search_parameters':{'q':'  "A/2026"  '},'organic_results':[]})
    assert r.status==SearchStatus.OK

@pytest.mark.parametrize('value', [None, {}, 'garbled'])
def test_missing_or_invalid_organic_state_cannot_support_assurance(value):
    payload={'search_metadata':{'status':'Success'}}
    if value is not None: payload['organic_results']=value
    r=response(payload)
    assert r.status==SearchStatus.ERROR


def test_provider_explicit_known_empty_state_is_supported():
    payload={'search_metadata':{'status':'Success'},
        'error':"Google hasn't returned any results for this query."}
    r=response(payload)
    assert r.status==SearchStatus.OK and r.results==()


def test_rejected_missing_link_records_cannot_be_silently_ignored():
    payload={'search_metadata':{'status':'Success'},'organic_results':[
        {'link':'https://issuer.example/a'},{'title':'Corrigendum A/2026'}]}
    r=response(payload)
    assert r.status==SearchStatus.ERROR and r.error_code=='PROVIDER_RESULTS_REJECTED'

@pytest.mark.asyncio
async def test_http_content_length_cap_is_checked_before_buffering():
    def handler(request):
        return httpx.Response(200,headers={'content-length':str(MAX_PROVIDER_BYTES+1)},content=b'{}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r=await SerpApiClient('test-secret',client=client).search(Q)
    assert r.status==SearchStatus.ERROR and r.error_code=='PROVIDER_BODY_TOO_LARGE'

@pytest.mark.asyncio
async def test_invalid_http_content_length_is_fail_closed():
    def handler(request):
        return httpx.Response(200,headers={'content-length':'unparseable'},content=b'{}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r=await SerpApiClient('test-secret',client=client).search(Q)
    assert r.status==SearchStatus.ERROR and r.error_code=='INVALID_PROVIDER_CONTENT_LENGTH'

@pytest.mark.asyncio
async def test_actual_streamed_bytes_limit_even_without_valid_header():
    class BigStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(4):
                yield b'z'*(MAX_PROVIDER_BYTES//3)
        async def aclose(self): pass
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,stream=BigStream()))) as client:
        r=await SerpApiClient('test-secret',client=client).search(Q)
    assert r.status==SearchStatus.ERROR and r.error_code=='PROVIDER_BODY_TOO_LARGE'


def ss(t=T):
    b=b'<main>Reference A/2026</main>'
    return SourceSnapshot(source_url='https://issuer.example/a',final_url='https://issuer.example/a',
        captured_at=t,content_type='text/html',body=b,body_sha256=sha256(b).hexdigest())

@pytest.mark.parametrize('num,byte_limit',[(0,2000),(2,0)])
def test_invalid_snapshot_capacity_configuration_is_rejected(tmp_path,num,byte_limit):
    with pytest.raises(ValueError,match='INVALID_EVIDENCE_STORAGE_BUDGET'):
        SnapshotStore(tmp_path,max_snapshots=num,max_total_bytes=byte_limit)

def test_capacity_checks_preserve_distinct_timestamps_and_exact_replay(tmp_path):
    store=SnapshotStore(tmp_path,max_snapshots=2)
    a=store.put(ss())
    assert a==store.put(ss()) # exact same envelope is idempotent
    b=store.put(ss(T+timedelta(seconds=1)))
    assert a!=b
    with pytest.raises(SourceFailure,match='OVERSIZED'):
        store.put(ss(T+timedelta(seconds=2)))
    assert store.get(a).body==store.get(b).body


def test_byte_budget_abstains_without_eviction(tmp_path):
    store=SnapshotStore(tmp_path,max_total_bytes=1)
    with pytest.raises(SourceFailure,match='OVERSIZED'):
        store.put(ss())
    assert list(tmp_path.glob('*.json'))==[]

@pytest.mark.parametrize('path', ['/notices/%2e%2e/other','/notices/%252e%252e%252fother',
                              '/notices/%255cprivate', '/notices/../community-uploads/test'])
def test_publication_path_denies_ambiguous_or_traversal_source(path):
    att=AuthorityAttestation(issuer_id='audit',exact_host='issuer.example',
        verification_evidence_url='https://issuer.example/',canonical_issuer_name='Test',
        verification_method='MANUAL_CROSS_LINK',verified_at=T,
        publication_path_prefixes=('/notices',))
    r=IssuerAuthorityRegistry((att,))
    assert r.verified('audit','https://issuer.example'+path) is False


def test_unescaped_percent_in_publication_path_is_not_authorized():
    att=AuthorityAttestation(issuer_id='audit',exact_host='issuer.example',
        verification_evidence_url='https://issuer.example/',canonical_issuer_name='Test',
        verification_method='MANUAL_CROSS_LINK',verified_at=T,
        publication_path_prefixes=('/notices',))
    registry=IssuerAuthorityRegistry((att,))
    assert registry.verified('audit','https://issuer.example/notices/file%broken.pdf') is False


@pytest.mark.asyncio
async def test_owned_serpapi_client_can_close_without_live_requests():
    client=SerpApiClient('test-only-never-dispatched')
    await client.aclose()
    assert client._client.is_closed


def test_direct_replay_adapter_rejects_oversized_parsed_dict():
    payload={'search_metadata':{'status':'Success'},'organic_results':[],
             'unused': 'X'*(MAX_PROVIDER_BYTES+100)}
    result=response(payload)
    assert result.status==SearchStatus.ERROR
    assert result.error_code=='PROVIDER_BODY_TOO_LARGE'

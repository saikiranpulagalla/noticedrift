"""New, independent v0.8.4 tests: provider response integrity, outbound bounds,
per-response reuse accounting, provider trust claims and startup recovery.
This suite is kept outside the original uploaded source directory.
"""
from __future__ import annotations
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.application.workflow import NoticeWorkflow
from app.application.models import NoticeCheckRequest, CheckOutcome
from app.domain.enums import EvidenceCoverage, Verdict
from app.domain.models import AnalysisResult
from app.search.client import SerpApiClient, parse_provider_payload
from app.search.executor import SearchExecutor
from app.search.models import PlannedQuery, QueryPurpose, QueryTier, SearchMode, SearchStatus
from app.sources import SafeSourceFetcher, AuthorityAttestation, IssuerAuthorityRegistry

ORIGINAL='https://issuer.example/notices/original'
ORIG=b'<main><h1>Notice</h1><p>Reference: A/2026</p><p>Issued: 2026-09-01</p><p>Application deadline: 01 October 2026</p></main>'

def q(): return PlannedQuery(query='"A/2026"',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=10)

def req(): return NoticeCheckRequest(issuer_id='test',issuer_name='Test Issuer',reference_number='A/2026',original_url=ORIGINAL,supplied_deadline=date(2026,10,1),as_of=datetime(2026,10,8,tzinfo=timezone.utc))

class Client:
    def __init__(self, organic): self.organic=organic;self.calls=0
    async def search(self,planned,**kw):
        self.calls+=1
        return parse_provider_payload({'search_metadata':{'status':'Success'},'organic_results':self.organic},planned,captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)

class Transport:
    def get(self, url,max_bytes):
        assert url==ORIGINAL
        return 200,{'content-type':'text/html'},ORIG

def workflow(organic):
    att=AuthorityAttestation(issuer_id='test',exact_host='issuer.example',verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK',verification_evidence_url='https://directory.example/record')
    return NoticeWorkflow(executor=SearchExecutor(Client(organic),simulation=True),fetcher=SafeSourceFetcher(transport=Transport()),registry=IssuerAuthorityRegistry((att,)),evidence_mode='SYNTHETIC_OFFLINE')


def test_partial_valid_organic_results_must_not_be_marked_fully_ok():
    valid={'link': ORIGINAL,'title':'Original government notice A/2026'}
    rejected={'link':'javascript:evil()','title':'Corrigendum for A/2026','snippet':'deadline extended'}
    result=parse_provider_payload({'search_metadata':{'status':'Success'},'organic_results':[valid,rejected]},q(),captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)
    print('PARTIAL_URL_RESULT',result.status,'admitted',len(result.results),'input',2,'error',result.error_code)
    assert result.status is SearchStatus.ERROR or len(result.results)==2, 'Result silently dropped without partial/error status'

@pytest.mark.asyncio
async def test_dropped_related_search_record_cannot_justify_positive_freshness():
    original={'link': ORIGINAL,'title':'Official A/2026'}
    malformed_correction={'link':'javascript:evil()','title':'Corrigendum A/2026','snippet':'Deadline extended to 26 October 2026'}
    w=workflow([original,malformed_correction])
    outcome=await w.check(req())
    print('DROPPED_RELATED_CANDIDATE_VERDICT',outcome.analysis.verdict,'calls',outcome.provider_calls)
    assert outcome.analysis.verdict is Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_success_metadata_without_organic_results_requires_explicit_empty_confirmation():
    client=Client([])
    original=client.search
    async def missing_results(planned,**kw):
        return parse_provider_payload({'search_metadata':{'status':'Success'}},planned,captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)
    client.search=missing_results
    w=workflow([])
    w.executor.client=client
    result=await w.check(req())
    print('MISSING_ORGANIC_KEY_VERDICT',result.analysis.verdict)
    assert result.analysis.verdict is Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_large_provider_json_body_must_be_bounded_before_parsing():
    big='X'*3_000_000
    payload={'search_metadata':{'status':'Success'},'organic_results':[], 'unused_debug_payload':big}
    encoded=json.dumps(payload).encode()
    def handler(request):return httpx.Response(200,content=encoded,headers={'content-type':'application/json'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client=SerpApiClient('test-not-real',client=http_client)
        response=await client.search(q())
    print('PROVIDER_BODY_BYTES',len(encoded),'STATUS',response.status,'ERROR',response.error_code)
    assert response.status is SearchStatus.ERROR and response.error_code in {'PROVIDER_BODY_TOO_LARGE','OVERSIZED_RESPONSE'}

@pytest.mark.asyncio
async def test_cached_api_response_reports_zero_new_provider_calls():
    class Engine:
        def __init__(self):self.calls=0
        async def check(self,request,*,fresh=True):
            self.calls+=1
            return CheckOutcome(analysis=AnalysisResult(verdict=Verdict.UNRESOLVED,coverage=EvidenceCoverage.INSUFFICIENT,family_id='x'),execution_mode='NETWORK',provider_calls=6)
    engine=Engine();app=create_app(engine)
    body=req().model_dump(mode='json')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as api:
        first=await api.post('/api/check',json=body)
        await asyncio.sleep(.03)
        reused=await api.post('/api/check',json=body)
    assert first.status_code==200 and reused.status_code==200
    print('API_REUSE', 'underlying_runs',engine.calls,'initial_calls',first.json()['provider_calls'],'reused_calls',reused.json()['provider_calls'],'mode',reused.json()['execution_mode'])
    assert engine.calls==1
    assert reused.json()['provider_calls']==0, 'Reused result falsely reports new paid calls for current request'

def test_provider_echoed_query_mismatch_must_not_count_as_completed_search():
    requested=q()
    payload={'search_metadata':{'status':'Success'},
             'search_parameters':{'engine':'google','q':'unrelated recruitment notice'},
             'organic_results':[{'link':ORIGINAL}]}
    response=parse_provider_payload(payload,requested,captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)
    print('QUERY_PROVENANCE',requested.query,'provider_echo',payload['search_parameters']['q'],'adapter_status',response.status)
    assert response.status is SearchStatus.ERROR, 'Provider acknowledged a different query but result treated as OK'

@pytest.mark.asyncio
async def test_mismatched_provider_query_cannot_produce_supported_by_evidence():
    w=workflow([{'link':ORIGINAL}])
    class EchoWrong:
        async def search(self,planned,**kwargs):
            return parse_provider_payload({'search_metadata':{'status':'Success'},'search_parameters':{'q':'UNRELATED_QUERY'},
              'organic_results':[{'link':ORIGINAL}]},planned,captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)
    w.executor.client=EchoWrong()
    out=await w.check(req())
    print('QUERY_MISMATCH_VERDICT',out.analysis.verdict)
    assert out.analysis.verdict is Verdict.UNRESOLVED

def test_control_well_formed_matching_serpapi_payload_is_accepted():
    response=parse_provider_payload({'search_metadata':{'status':'Success'},
        'search_parameters':{'engine':'google','q':'"A/2026"'},
        'organic_results':[{'link':ORIGINAL}]}, q(),captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)
    assert response.status is SearchStatus.OK
    assert len(response.results)==1

@pytest.mark.asyncio
async def test_control_original_and_valid_correction_still_resolve_as_superseded():
    correction='https://issuer.example/corrigendum'
    correction_body=b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\nThe deadline is extended from 01 October 2026 to 26 October 2026</main>'
    class TwoTransport:
        def get(self,url,max_bytes):return 200,{'content-type':'text/html'}, {ORIGINAL:ORIG, correction:correction_body}[url]
    att=AuthorityAttestation(issuer_id='test',exact_host='issuer.example',verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK',verification_evidence_url='https://directory.example/record')
    wf=NoticeWorkflow(executor=SearchExecutor(Client([{'link':ORIGINAL},{'link':correction}]),simulation=True),
        fetcher=SafeSourceFetcher(transport=TwoTransport()),registry=IssuerAuthorityRegistry((att,)),evidence_mode='SYNTHETIC_OFFLINE')
    result=await wf.check(req())
    assert result.analysis.verdict is Verdict.SUPERSEDED

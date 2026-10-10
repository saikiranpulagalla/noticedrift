"""Novel, offline security/consistency probes for unmodified NoticeDrift v0.8.3.
Run: PYTHONPATH=backend python -m pytest /mnt/data/audit_v083_final/test_final_new_angles.py -q
These assertions intentionally express stronger safety/reproducibility requirements.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
import sys
import time
from urllib.parse import quote
import pytest

from app.application.models import NoticeCheckRequest
from app.application.workflow import NoticeWorkflow
from app.domain.enums import Verdict
from app.search import SearchExecutor, SearchResponse, SearchMode, SearchStatus, OrganicResult
from app.sources import SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation
from app.sources.fetch import safe_target
from app.sources.store import SnapshotStore
import app.application.workflow as workflow_module

ORIGINAL='https://issuer.example/notices/original'
UPDATE='https://issuer.example/notices/update'
USER_UPLOAD='https://issuer.example/user-uploads/corrigendum.txt'
ORIGINAL_BODY=b'<main><h1>Official Notice</h1><p>Reference: A/2026</p><p>Issued: 2026-09-01</p><p>Application deadline: 01 October 2026</p></main>'
CORRECTION_BODY=b'<main><h1>Corrigendum</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p><p>The deadline is extended from 01 October 2026 to 26 October 2026.</p></main>'

class FakeTransport:
    def __init__(self, pages):
        self.pages=pages; self.calls=[]
    def get(self, url, max_bytes):
        self.calls.append(url)
        return 200,{'content-type': 'text/html'},self.pages[url]

class FakeSearch:
    def __init__(self, urls, fail_after=None):
        self.urls=urls; self.fail_after=fail_after;self.calls=0
    async def search(self, planned, **kwargs):
        self.calls+=1
        if self.fail_after and self.calls >= self.fail_after:
            raise RuntimeError('simulated provider outage mid-plan')
        return SearchResponse(query=planned, mode=SearchMode.SYNTHETIC,
            status=SearchStatus.OK,captured_at=datetime.now(timezone.utc),
            provider_cached=False,provider_status='Success',
            results=tuple(OrganicResult(link=url) for url in self.urls))

class FaultyStore:
    def put(self, snapshot):
        raise PermissionError('simulated disk-full/permission failure')


def prepare(pages=None, *, fail_after=None, store=None):
    pages=pages or {ORIGINAL:ORIGINAL_BODY,UPDATE:CORRECTION_BODY}
    client=FakeSearch(tuple(pages), fail_after=fail_after)
    transport=FakeTransport(pages)
    registry=IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='demo',
        exact_host='issuer.example', verification_evidence_url='https://directory.example/record',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))
    runner=NoticeWorkflow(executor=SearchExecutor(client,simulation=True),
        fetcher=SafeSourceFetcher(transport=transport),registry=registry,
        evidence_mode='SYNTHETIC_OFFLINE',snapshot_store=store)
    return runner,client,transport


def req(as_of=datetime(2026,10,8,tzinfo=timezone.utc)):
    return NoticeCheckRequest(issuer_id='demo',issuer_name='Demo Issuer',
        reference_number='A/2026', supplied_deadline=date(2026,10,1),as_of=as_of)

@pytest.mark.asyncio
async def test_same_instant_in_different_timezones_cannot_change_verdict():
    moment_utc=datetime(2026,9,18,0,10,tzinfo=timezone.utc)
    moment_pacific=moment_utc.astimezone(timezone(timedelta(hours=-7)))
    runner_a,_,_=prepare()
    runner_b,_,_=prepare()
    result_a=await runner_a.check(req(moment_utc))
    result_b=await runner_b.check(req(moment_pacific))
    print('TIMEZONE',str(moment_utc),str(moment_pacific),result_a.analysis.verdict,result_b.analysis.verdict)
    assert result_a.analysis.verdict == result_b.analysis.verdict


def test_percent_encoded_url_path_must_not_be_double_encoded_before_fetch():
    literal='https://issuer.example/recruitment/Circular%20No%201.pdf?download=%2Ffull%2F'
    scheme,host,port,path=safe_target(literal)
    sent=quote(path,safe='/%?&=:@+$,;~*-._!')
    print('PERCENT_ENCODING',path,'=>',sent)
    assert sent == path

@pytest.mark.asyncio
async def test_mid_search_failure_must_report_nonzero_provider_attempts():
    runner,client,_=prepare(fail_after=3)
    out=await runner.check(req())
    print('DISPATCH_FAILURE',client.calls,out.provider_calls,out.warnings)
    assert out.analysis.verdict == Verdict.UNRESOLVED
    assert out.provider_calls >= client.calls

@pytest.mark.asyncio
async def test_failed_evidence_persistence_abstains_without_server_crash():
    runner,client,_=prepare(store=FaultyStore())
    try:
        out=await runner.check(req())
    except Exception as e:
        pytest.fail(f'uncaught storage exception after paid/provider work: {type(e).__name__}')
    print('PERSISTENCE_FAILURE',out.analysis.verdict,out.warnings,client.calls)
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_parsing_large_sources_does_not_block_other_event_loop_tasks(monkeypatch):
    original_parse=workflow_module.parse_snapshot
    def slow_parse(*args,**kwargs):
        time.sleep(0.27)
        return original_parse(*args,**kwargs)
    monkeypatch.setattr(workflow_module,'parse_snapshot',slow_parse)
    runner,_,_=prepare()
    start=time.perf_counter()
    heartbeat=asyncio.create_task(asyncio.sleep(0.03))
    task=asyncio.create_task(runner.check(req()))
    await heartbeat
    elapsed=time.perf_counter()-start
    out=await task
    print('LOOP_DELAY',round(elapsed,3), 'verdict=',out.analysis.verdict)
    assert elapsed < 0.15

@pytest.mark.asyncio
async def test_host_attestation_cannot_authorize_user_uploaded_notice_path():
    pages={ORIGINAL:ORIGINAL_BODY, USER_UPLOAD:CORRECTION_BODY}
    runner,_,_=prepare(pages)
    out=await runner.check(req())
    print('USER_CONTROLLED_PATH',out.analysis.verdict,[(x.url,x.role) for x in out.sources])
    assert out.analysis.verdict == Verdict.UNRESOLVED

def test_public_demo_api_enforces_request_body_size_limit():
    from fastapi.testclient import TestClient
    from app.api.main import create_app
    padding=' ' * 2_100_000
    data='{"supplied_deadline":"2026-10-01"}' + padding
    with TestClient(create_app(None)) as client:
        r=client.post('/api/demo/check',content=data,headers={'Content-Type':'application/json'})
    print('OVERSIZED_BODY',len(data),'status',r.status_code)
    assert r.status_code == 413

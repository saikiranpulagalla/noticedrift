"""Safety-regression interactions added after v0.8 independent red-team audit."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"application"))
import pytest
from fastapi.testclient import TestClient
from app.api.main import create_app, configured_workflow
from app.api.site import SITE
from app.application.models import CheckOutcome
from app.domain.enums import EvidenceCoverage, Verdict
from app.domain.models import AnalysisResult
from app.search.executor import SearchExecutor
from app.search.models import PlannedQuery, SearchPlan, QueryPurpose, QueryTier, SearchResponse, SearchMode, SearchStatus
from app.search.budget import SharedCreditLedger
from app.search.planner import plan_queries
from app.sources.models import SourceSnapshot
from app.sources.parse import parse_snapshot
from hashlib import sha256

@pytest.mark.parametrize('ref',["ABC\" site:attacker.example \"", 'A\nB', '(site:private.example)', 'x'*121])
def test_unsafe_reference_is_not_silently_rewritten(ref):
    assert plan_queries(reference_number=ref,issuer_name='Issuer',title=None).queries == ()

@pytest.mark.parametrize('ref',['ADV-OR-17/2026','A-AND-B-17/2026','ADV/01/2026'])
def test_safe_literal_reference_keeps_full_identity_in_core(ref):
    plan=plan_queries(reference_number=ref,issuer_name='Issuer',title=None)
    core=[x for x in plan.queries if x.tier==QueryTier.CORE]
    assert len(core)==4
    assert all(f'"{ref}"' in x.query for x in core)

@pytest.mark.parametrize('style', ['opacity:0','filter:opacity(0)','transform:translateX(-10000px)',
    'font-size:0px','clip-path:circle(0)','color:transparent','display:none','visibility:hidden'])
def test_hidden_root_abstains(style):
    html=f'<main style="{style}"><p>Application deadline is 26 October 2026.</p></main>'.encode()
    snap=SourceSnapshot(source_url='https://i.example/a',final_url='https://i.example/a',
        captured_at=datetime.now(timezone.utc),content_type='text/html',body=html,
        body_sha256=sha256(html).hexdigest())
    parsed=parse_snapshot(snap)
    assert parsed.status != 'PARSED'

@pytest.mark.parametrize('style', ['opacity:0','transform:translateX(-10000px)','clip-path:circle(0)'])
def test_unknown_descendant_visibility_blocks_positive_evidence(style):
    html=(f'<main><p>Visible official statement.</p><p style="{style}">New deadline 26 October</p></main>').encode()
    snap=SourceSnapshot(source_url='https://i.example/a',final_url='https://i.example/a',
        captured_at=datetime.now(timezone.utc),content_type='text/html',body=html,
        body_sha256=sha256(html).hexdigest())
    parsed=parse_snapshot(snap)
    assert parsed.status == 'PARTIAL'
    assert 'HTML_PERCEPTIBILITY_UNVERIFIED' in parsed.warning_codes
    assert 'New deadline' not in parsed.text


def test_visible_judge_live_form_is_not_a_fake_live_verdict():
    assert 'id="live-form"' in SITE and '/api/check' in SITE
    assert 'Live checks are disabled' in SITE
    app=create_app(None)
    with TestClient(app) as client:
        assert client.get('/api/capabilities').json()['live_enabled'] is False
        assert client.get('/').status_code == 200


@pytest.mark.asyncio
async def test_global_api_limiter_bounds_simultaneous_expensive_checks():
    class Slow:
        async def check(self, req, *, fresh=True):
            await asyncio.sleep(.05)
            return CheckOutcome(analysis=AnalysisResult(verdict=Verdict.UNRESOLVED,
                coverage=EvidenceCoverage.INSUFFICIENT, family_id='x'),execution_mode='NETWORK',provider_calls=0)
    import httpx
    from test_v07_workflow import request
    app=create_app(Slow())
    reqs=[{**request().model_dump(mode='json'),'supplied_deadline':f'2026-10-{i:02d}'} for i in range(1,9)]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://t') as client:
        responses=await asyncio.gather(*(client.post('/api/check',json=req) for req in reqs))
    assert sum(r.status_code==200 for r in responses)<=4
    assert sum(r.status_code==429 for r in responses)>=4


@pytest.mark.asyncio
async def test_identical_live_checks_share_one_inflight_task():
    class Slow:
        def __init__(self):self.calls=0
        async def check(self, req, *, fresh=True):
            self.calls+=1
            await asyncio.sleep(.04)
            return CheckOutcome(analysis=AnalysisResult(verdict=Verdict.UNRESOLVED,
                coverage=EvidenceCoverage.INSUFFICIENT, family_id='x'),execution_mode='NETWORK',provider_calls=0)
    import httpx
    from test_v07_workflow import request
    engine=Slow();app=create_app(engine);body=request().model_dump(mode='json')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://t') as client:
        results=await asyncio.gather(*(client.post('/api/check',json=body) for _ in range(10)))
    assert engine.calls==1 and all(x.status_code==200 for x in results)
    assert any(x.json()['execution_mode'].endswith('_INFLIGHT_SHARED') for x in results)


@pytest.mark.asyncio
async def test_exhausted_credit_is_not_counted_as_dispatched(tmp_path):
    ledger=SharedCreditLedger(tmp_path/'quota.db',monthly_limit=1)
    assert ledger.reserve()
    class Client:
        def __init__(self):self.calls=0
        async def search(self, planned, **params):
            self.calls+=1
            return SearchResponse(query=planned, mode=SearchMode.LIVE,status=SearchStatus.OK,
                captured_at=datetime.now(timezone.utc),provider_cached=False,provider_status='Success')
    client=Client();from app.search.cache import LiveSearchCache
    executor=SearchExecutor(client,cache=LiveSearchCache(tmp_path/'cache'),ledger=ledger)
    q=PlannedQuery(query='"A/2026"',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    run=await executor.execute(SearchPlan(queries=(q,),max_calls=8),fresh=False,allow_local_cache=True)
    assert client.calls == run.attempts == 0
    assert run.coverage == EvidenceCoverage.INSUFFICIENT
    assert ledger.used()==1


def test_configuration_array_validation_is_controlled(monkeypatch,tmp_path):
    p=tmp_path/'hosts.json';p.write_text('[{}, 42]')
    monkeypatch.setenv('SERPAPI_API_KEY','synthetic-key')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(p))
    assert configured_workflow() is None


@pytest.mark.asyncio
async def test_recent_completed_check_is_truthfully_labelled_as_reused():
    import httpx
    from test_v07_workflow import request
    class Engine:
        def __init__(self):self.calls=0
        async def check(self,req,*,fresh=True):
            self.calls+=1
            return CheckOutcome(analysis=AnalysisResult(verdict=Verdict.UNRESOLVED,
                coverage=EvidenceCoverage.INSUFFICIENT, family_id='x'),
                execution_mode='NETWORK',provider_calls=0)
    engine=Engine();app=create_app(engine);body=request().model_dump(mode='json')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://t') as client:
        r1=await client.post('/api/check',json=body)
        await asyncio.sleep(.01)  # allow the scheduled cleanup to populate recent
        r2=await client.post('/api/check',json=body)
    assert r1.status_code==r2.status_code==200
    assert engine.calls==1
    assert r2.json()['execution_mode'].endswith('_RECENT_SHARED')


def test_bad_operator_quota_fails_closed(monkeypatch,tmp_path):
    import json
    p=tmp_path/'authority.json'
    p.write_text(json.dumps([{'issuer_id':'gov','exact_host':'issuer.example',
        'verification_evidence_url':'https://directory.example/record',
        'verified_at':'2026-09-01T00:00:00Z',
        'verification_method':'MANUAL_CROSS_LINK'}]))
    monkeypatch.setenv('SERPAPI_API_KEY','fake-test-credential')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(p))
    monkeypatch.setenv('NOTICEDRIFT_MONTHLY_SEARCH_LIMIT','999999')
    assert configured_workflow() is None


def test_dark_text_on_dark_pdf_fill_cannot_govern():
    import fitz
    doc=fitz.open();page=doc.new_page()
    page.draw_rect(fitz.Rect(0,0,595,842),color=(0,0,0),fill=(0,0,0))
    page.insert_text((60,90),'The deadline is extended from 01 October 2026 to 26 October 2026.',
        fontsize=10,color=(0,0,0))
    body=doc.tobytes();doc.close()
    snapshot=SourceSnapshot(source_url='https://i.example/a',final_url='https://i.example/a',
        captured_at=datetime.now(timezone.utc),content_type='application/pdf',body=body,
        body_sha256=sha256(body).hexdigest())
    parsed=parse_snapshot(snapshot)
    assert parsed.status=='PARTIAL'
    assert 'PDF_BACKGROUND_PERCEPTIBILITY_UNVERIFIED' in parsed.warning_codes


def test_partly_transparent_html_is_not_certified_visible():
    html=b'<main style="opacity:0.03"><p>Deadline extended to 26 October 2026</p></main>'
    snapshot=SourceSnapshot(source_url='https://i.example/a',final_url='https://i.example/a',
        captured_at=datetime.now(timezone.utc),content_type='text/html',body=html,
        body_sha256=sha256(html).hexdigest())
    assert parse_snapshot(snapshot).status != 'PARSED'

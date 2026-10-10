from __future__ import annotations
from datetime import datetime, timezone, date
from hashlib import sha256
from unittest.mock import patch
import pytest
import httpx
from app.application.extract import date_value,extract_notice,ExtractionUnresolved
from app.application.models import NoticeCheckRequest
from app.application.workflow import NoticeWorkflow
from app.api.main import create_app
from app.domain.enums import Verdict
from app.sources.models import ParsedSource
from test_v07_workflow import (
    workflow,request,ORIGINAL,UPDATE,ORIG_HTML,UPDATE_HTML,CANCEL_HTML,
    FakeSearch,FakeTransport,
)

def parsed(text,status='PARSED'):
    return ParsedSource(snapshot_sha256='a'*64,
                        normalized_text_sha256=sha256(text.encode()).hexdigest(),
                        text=text,status=status)

@pytest.mark.parametrize('bad',[
    'not a date','2026-13-01','31 February 2026','01 September 202x','01/10/2026','2026-01-01 00:00',
])
def test_unsupported_dates_fail_closed(bad):
    with pytest.raises(ExtractionUnresolved): date_value(bad)

@pytest.mark.parametrize('correct,expected',[
    ('01 October 2026',date(2026,10,1)),
    ('2026-10-26',date(2026,10,26)),
])
def test_supported_dates(correct,expected):
    assert date_value(correct)==expected

@pytest.mark.parametrize('text',[
    'Reference: A/2026\nIssued: 2026-09-01\nLast date: 01 October 2026\nCorrigendum issued',
    'Reference: A/2026\nIssued: 2026-09-01\nLast date: 01 October 2026\nLast date: 26 October 2026',
    'Reference: A/2026\nIssued: 2026-09-01\nThe deadline is extended from 01 October 2026 to 26 October 2026 for post A',
    'Reference: A/2026\nThe deadline is extended from 01 October 2026 to 26 October 2026',
    'Reference: A/2026\nIssued: 2026-09-01\nLast date: 01 October 2026\nIssued: 2026-10-01',
    'Reference: A/2026\nReference: A/2026\nIssued: 2026-09-01\nLast date: 01 October 2026',
    'Reference: B/2026\nIssued: 2026-09-01\nLast date: 01 October 2026',
    'Reference: A/2026\nIssued: 2026-09-01\nLast date: 01 October 2026\nThe recruitment is cancelled',
    'Reference: A/2026\nIssued: 2026-09-01\nThe recruitment is cancelled.\nThe deadline is extended from 01 October 2026 to 26 October 2026',
])
def test_unsafe_notice_patterns_abstain(text):
    with pytest.raises(ExtractionUnresolved): extract_notice(parsed(text),'A/2026')

def test_no_inference_from_partial_parser():
    text='Reference: A/2026\nIssued: 2026-09-01\nLast date: 01 October 2026'
    with pytest.raises(ExtractionUnresolved): extract_notice(parsed(text,'PARTIAL'),'A/2026')

def test_simple_cancel_extraction():
    info=extract_notice(parsed('Reference: A/2026\nIssued: 2026-09-17\nThis recruitment is cancelled'), 'A/2026')
    assert info.role.value=='CANCELLATION'
    assert info.deadline is None

@pytest.mark.asyncio
async def test_api_health_and_capabilities_without_configuration():
    app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        health=await client.get('/health')
        capabilities=await client.get('/api/capabilities')
        assert health.status_code==200 and health.json()['status']=='ok'
        assert capabilities.status_code==200
        assert capabilities.json()['live_enabled'] is False
        assert 'full_cancellation' in capabilities.json()['supported_relations']

@pytest.mark.asyncio
async def test_api_fails_closed_when_unconfigured():
    app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/check',json=request().model_dump(mode='json'))
    assert response.status_code==503 and response.json()['detail']=='LIVE_SEARCH_NOT_CONFIGURED'

@pytest.mark.asyncio
async def test_api_uses_injected_synthetic_workflow():
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    app=create_app(w)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/check',json=request().model_dump(mode='json'))
    assert response.status_code==200,response.text
    assert response.json()['analysis']['verdict']=='SUPERSEDED'
    assert response.json()['execution_mode'].startswith('SYNTHETIC_OFFLINE')

@pytest.mark.asyncio
async def test_api_invalid_input_rejected():
    w,_,_=workflow([ORIGINAL],{ORIGINAL:ORIG_HTML})
    app=create_app(w)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/check',json={**request().model_dump(mode='json'), 'issuer_id':''})
    assert response.status_code==422

@pytest.mark.asyncio
async def test_multi_extension_chain():
    second='https://issuer.example/second'
    extra=b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-20\nThe deadline is extended from 26 October 2026 to 30 October 2026</main>'
    w,_,_=workflow([ORIGINAL,UPDATE,second],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML,second:extra})
    out=await w.check(request())
    assert out.analysis.verdict==Verdict.SUPERSEDED,out.model_dump()
    assert out.analysis.field_resolutions[0].value==date(2026,10,30)

@pytest.mark.asyncio
async def test_future_issued_update_does_not_fake_new_current_deadline():
    future=UPDATE_HTML.replace(b'2026-09-17',b'2026-10-20')
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:future})
    out=await w.check(request())
    # A future-issued notice cannot justify positive assurance as of Oct 8 either.
    assert out.analysis.verdict != Verdict.SUPERSEDED

@pytest.mark.asyncio
async def test_multiple_originals_cannot_choose_arbitrarily():
    duplicate='https://issuer.example/second-notice'
    new_original=ORIG_HTML.replace(b'01 October 2026',b'15 October 2026')
    w,_,_=workflow([ORIGINAL,duplicate],{ORIGINAL:ORIG_HTML,duplicate:new_original})
    out=await w.check(request())
    assert out.analysis.verdict==Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_source_candidate_limit_fail_closed():
    urls=[f'https://issuer.example/{i}' for i in range(13)]
    w,_,transport=workflow(urls,{})
    out=await w.check(request())
    assert out.analysis.verdict==Verdict.UNRESOLVED
    assert not transport.calls

@pytest.mark.asyncio
async def test_wrong_original_url_host_does_not_initiate_search():
    w,search,transport=workflow([ORIGINAL],{ORIGINAL:ORIG_HTML})
    out=await w.check(request(url='https://evil.example/source'))
    assert out.analysis.verdict==Verdict.UNRESOLVED
    assert not search.calls and not transport.calls

def test_bad_config_not_enabled(monkeypatch,tmp_path):
    from app.api.main import configured_workflow
    monkeypatch.delenv('SERPAPI_API_KEY',raising=False)
    monkeypatch.delenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',raising=False)
    assert configured_workflow() is None
    monkeypatch.setenv('SERPAPI_API_KEY','dummy')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(tmp_path/'missing.json'))
    assert configured_workflow() is None

def test_empty_config_not_live(monkeypatch,tmp_path):
    from app.api.main import configured_workflow
    p=tmp_path/'hosts.json';p.write_text('[]')
    monkeypatch.setenv('SERPAPI_API_KEY','dummy')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(p))
    assert configured_workflow() is None

@pytest.mark.parametrize('mode',['bogus','LIVE_PRETEND'])
def test_workflow_rejects_false_mode(mode):
    w,s,t=workflow([ORIGINAL],{ORIGINAL:ORIG_HTML})
    with pytest.raises(ValueError): NoticeWorkflow(executor=w.executor,fetcher=w.fetcher,registry=w.registry,evidence_mode=mode)

def test_valid_operator_config_can_construct_live_runner_without_network(monkeypatch,tmp_path):
    from app.api.main import configured_workflow
    p=tmp_path/'hosts.json'
    p.write_text('[{"issuer_id":"gov-a","exact_host":"authority.example",'
                 '"verification_evidence_url":"https://directory.example/entry",'
                 '"verified_at":"2026-10-08T08:00:00Z",'
                 '"verification_method":"MANUAL_CROSS_LINK",'
                 '"canonical_issuer_name":"Government Authority A",'
                 '"publication_path_prefixes":["/notices"]}]')
    monkeypatch.setenv('SERPAPI_API_KEY','fake-for-construction-only')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(p))
    engine=configured_workflow()
    assert engine is not None
    assert 'authority.example' in engine.registry.approved_hosts('gov-a')
    assert engine.evidence_mode == 'NETWORK'


def test_large_attestation_config_is_not_enabled(monkeypatch,tmp_path):
    from app.api.main import configured_workflow
    p=tmp_path/'hosts.json';p.write_text(' ' * 35000)
    monkeypatch.setenv('SERPAPI_API_KEY','fake')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(p))
    assert configured_workflow() is None


def test_operator_config_not_array_is_rejected(monkeypatch,tmp_path):
    from app.api.main import configured_workflow
    p=tmp_path/'hosts.json';p.write_text('{}')
    monkeypatch.setenv('SERPAPI_API_KEY','fake')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(p))
    # Invalid operator configuration fails closed without crashing startup.
    assert configured_workflow() is None

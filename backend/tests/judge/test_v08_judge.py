"""Safety regression tests: honesty and offline judge experience."""
from __future__ import annotations
from datetime import date, datetime, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.api.main import create_app
from app.application.demo import run_demo, DemoSearch
from app.application.reference_case import official_reference_case
from app.domain.enums import Verdict, EvidenceCoverage
from app.search import SearchExecutor, SearchMode
from app.search.planner import plan_queries

@pytest.fixture
def client():
    return TestClient(create_app(None))

def test_landing_page_self_contained_and_accurate(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert '<!doctype html>' in resp.text
    assert 'The notice was real.' in resp.text
    assert 'fully executable synthetic' not in resp.text.lower() or 'synthetic' in resp.text.lower()
    # Explicit semantic markers prevent the recorded live diagnostic and the
    # executable synthetic fixture from being presented as the same evidence.
    assert 'data-evidence-mode="SYNTHETIC_OFFLINE"' in resp.text
    assert 'data-evidence-kind="RECORDED_LIVE_SEARCH_DIAGNOSTIC"' in resp.text
    assert 'mocked SerpApi responses' in resp.text
    assert 'SYNTHETIC · offline fixture' in resp.text
    assert 'never a live SerpApi response' in resp.text
    assert 'Recorded live-search diagnostic' in resp.text
    assert 'not an automated live result' in resp.text.lower()
    assert 'no-store' in resp.headers['cache-control']
    assert 'frame-ancestors' in resp.headers['content-security-policy']
    assert '<script src="http' not in resp.text

def test_reference_case_is_not_laundered_into_live_evidence(client):
    result = client.get('/api/reference-case')
    assert result.status_code == 200
    c = result.json()
    assert c['original_deadline'] == '2026-10-01'
    assert c['revised_deadline'] == '2026-10-26'
    assert c['correction_published'] == '2026-09-17'
    assert c['application_snapshot_verified'] is False
    assert c['serpapi_run_executed'] is False
    assert c['automated_governance_verdict'] is None
    assert c['other_material_change']['machine_verified'] is False
    assert c['other_material_change']['original']=='Physiology'
    assert c['other_material_change']['corrected']=='Psychology'
    assert all(x['url'].startswith('https://nicf.gov.in/') for x in c['references'])

def test_recorded_live_diagnostic_is_sanitized_and_never_claims_source_evidence(client):
    diagnostic = client.get('/api/live-search-diagnostic')
    assert diagnostic.status_code == 200
    payload = diagnostic.json()
    assert payload['kind'] == 'SANITIZED_RECORDED_LIVE_SEARCH_DIAGNOSTIC'
    assert payload['provider_attempts'] == 6
    assert payload['completed_attempts'] == 2
    assert payload['timed_out_attempts'] == 4
    assert payload['coverage'] == 'INSUFFICIENT'
    assert payload['verdict'] == 'UNRESOLVED'
    assert payload['official_source_captures'] == 0
    assert payload['source_evidence_authenticated'] is False
    assert all('query' not in entry and 'url' not in entry for entry in payload['attempts'])
    assert [(entry['purpose'], entry['status'], entry['elapsed_ms']) for entry in payload['attempts']] == [
        ('IDENTITY', 'OK', 1547),
        ('CORE_CORRIGENDUM', 'TIMEOUT', 15016),
        ('CORE_EXTENSION', 'OK', 937),
        ('CORE_CANCELLATION', 'TIMEOUT', 15016),
        ('OFFICIAL_SITE_CORRIGENDUM', 'TIMEOUT', 15016),
        ('OFFICIAL_SOURCE_IDENTITY', 'TIMEOUT', 15016),
    ]
    page = client.get('/').text
    assert 'Separate live discovery attempts did not establish an authenticated governing deadline.' in page
    assert 'Identity and core extension discovery' in page
    assert 'Core corrigendum, cancellation, official-site corrigendum, official-source identity' in page

def test_offline_api_outdated_deadline(client,monkeypatch):
    def no_live(*args,**kwargs):
        raise AssertionError('LIVE_PROVIDER_USED_IN_OFFLINE_DEMO')
    from app.search.client import SerpApiClient
    monkeypatch.setattr(SerpApiClient,'search',no_live)
    r = client.post('/api/demo/check',json={'supplied_deadline':'2026-10-01'})
    assert r.status_code == 200, r.text
    j=r.json()
    assert j['analysis']['verdict']=='SUPERSEDED'
    assert j['analysis']['field_resolutions'][0]['value']=='2026-10-26'
    assert j['execution_mode'].startswith('SYNTHETIC_OFFLINE')
    assert 0 < j['provider_calls'] <= 8  # attempted mock invocations, not credits
    assert len(j['sources'])==2
    assert all(x['mode']=='SYNTHETIC' for x in j['search_entries'])
    assert all(x['authority_attested'] for x in j['sources'])

def test_offline_api_updated_deadline(client):
    r=client.post('/api/demo/check',json={'supplied_deadline':'2026-10-26'})
    assert r.status_code==200
    j=r.json()
    assert j['analysis']['verdict']=='SUPPORTED_BY_EVIDENCE'
    assert j['execution_mode'].startswith('SYNTHETIC_OFFLINE')

def test_offline_demo_never_needs_live_credentials(client,monkeypatch):
    monkeypatch.delenv('SERPAPI_API_KEY',raising=False)
    r=client.get('/api/capabilities');assert r.json()['live_enabled'] is False
    assert client.post('/api/check',json={}).status_code==422
    assert client.get('/health').json()['configured'] is False
    # Health reports the current release, not the earlier v0.8.1 fixture version.
    assert client.get('/health').json()['version']=='v0.8.5'

def test_live_api_without_credentials_fails_closed(client):
    request = {'issuer_id':'nca-f', 'issuer_name':'National Communications Academy Finance',
               'reference_number':'4-22/Teaching Associate/2026-NCA-F',
               'supplied_deadline':'2026-10-01','as_of':'2026-10-08T12:00:00Z'}
    r=client.post('/api/check',json=request)
    assert r.status_code==503
    assert r.json()['detail']=='LIVE_SEARCH_NOT_CONFIGURED'

def test_demo_api_rejects_unsupported_payloads(client):
    assert client.post('/api/demo/check',json={'supplied_deadline':'bad'}).status_code==422
    assert client.post('/api/demo/check',json={'supplied_deadline':'2026-10-01','issuer_host':'attacker.example'}).status_code == 422

def test_reference_data_not_dependent_on_api_credentials():
    c=official_reference_case()
    assert c['case_type']=='REAL_OFFICIAL_SOURCE_REFERENCE'
    assert 'not' in c['disclosure'].lower()

@pytest.mark.asyncio
async def test_synthetic_mode_never_qualifies_as_live_coverage():
    plan=plan_queries(reference_number='A/2026',issuer_name='Fixture Issuer',title=None,official_domain='issuer.example')
    result=await SearchExecutor(DemoSearch()).execute(plan,fresh=True)
    assert result.coverage != EvidenceCoverage.ADEQUATE
    assert all(x.mode == SearchMode.SYNTHETIC for x in result.responses)

@pytest.mark.asyncio
async def test_offline_demo_is_repeatable_and_immutable():
    first=await run_demo(date(2026,10,1))
    second=await run_demo(date(2026,10,1))
    assert first.analysis.verdict == second.analysis.verdict == Verdict.SUPERSEDED
    assert tuple(x.source_sha256 for x in first.sources)==tuple(x.source_sha256 for x in second.sources)
    assert tuple(x.relation_quote for x in first.sources)==tuple(x.relation_quote for x in second.sources)

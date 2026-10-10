"""Official-title discovery is not issuer authority. No network in these tests."""
from __future__ import annotations
import os
from datetime import date, datetime, timezone
from pathlib import Path
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from app.api.main import create_app
from app.application.models import NoticeCheckRequest
from app.search.models import QueryPurpose, QueryTier
from app.search.planner import plan_queries

REFERENCE = '4-22/Estt./Teaching Associates/2026-NCA-F'
HOST = 'nicf.gov.in'

def test_title_alias_search_stays_under_fixed_budget_and_preserves_identity():
    plan = plan_queries(reference_number=REFERENCE,
        issuer_name='National Communications Academy Finance',
        title='Teaching Associates', official_domain=HOST)
    assert 1 <= len(plan.queries) <= 8
    core = [q for q in plan.queries if q.tier is QueryTier.CORE]
    assert len(core) == 4
    assert all('4-22/ESTT./TEACHING ASSOCIATES/2026-NCA-F' in q.query for q in core)
    assert any(q.tier is QueryTier.EXPANSION and q.purpose is QueryPurpose.AMENDMENT
                   and 'site:nicf.gov.in' in q.query and '"Teaching Associates" corrigendum' in q.query
                   for q in plan.queries)

def test_untrusted_title_cannot_change_issuer_host_or_paid_call_cap():
    plan = plan_queries(reference_number=REFERENCE, issuer_name='Government',
        title='Teaching Associates" site:attacker.example OR', official_domain=HOST)
    assert 1 <= len(plan.queries) <= 8
    assert all('site:attacker.example' not in q.query for q in plan.queries)
    assert all('attacker.example' not in q.query for q in plan.queries)
    assert all('4-22/ESTT./TEACHING ASSOCIATES/2026-NCA-F' in q.query
               for q in plan.queries if q.tier is QueryTier.CORE)

def test_title_is_search_hint_not_an_authority_input():
    req = NoticeCheckRequest(issuer_id='ncaf', issuer_name='National Communications Academy Finance',
        reference_number=REFERENCE, notice_title='Teaching Associates',
        supplied_deadline=date(2026,10,1), as_of=datetime(2026,10,9,tzinfo=timezone.utc))
    assert req.notice_title == 'Teaching Associates'
    assert 'trusted_host' not in NoticeCheckRequest.model_fields
    assert 'authority_attestation' not in NoticeCheckRequest.model_fields

def test_judge_live_form_preset_matches_operator_manifest_and_records_search_manifest():
    from app.api.site import SITE
    assert 'id="live-id"' in SITE and 'value="ncaf"' in SITE
    assert 'id="live-ref"' in SITE and f'value="{REFERENCE}"' in SITE
    assert 'id="live-title"' in SITE
    assert 'notice_title:q' in SITE
    assert 'SerpApi discovery audit trail' in SITE
    assert 'entry.provider_cached' in SITE
    assert 'out.search_entries.slice(0,8)' in SITE

def test_offline_mode_never_implies_live_authentication():
    with TestClient(create_app(None)) as client:
        assert client.get('/api/capabilities').json()['live_enabled'] is False
        assert client.get('/health').json()['version'] == 'v0.8.5'
        assert client.post('/api/check', json={}).status_code == 422

def test_real_case_preflight_no_key_and_explicit_refusal_without_key(tmp_path):
    root=Path(__file__).resolve().parents[3]
    script=root/'scripts'/'live_ncaf_check.py'
    env={k:v for k,v in os.environ.items() if k != 'SERPAPI_API_KEY'}
    plan=subprocess.run([sys.executable,str(script)],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
    assert plan.returncode==0
    assert 'DRY_RUN_NO_REQUESTS' in plan.stdout
    assert 'Teaching Associates' in plan.stdout
    live=subprocess.run([sys.executable,str(script),'--execute'],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
    assert live.returncode==2
    assert 'SERPAPI_API_KEY not present' in live.stderr

@pytest.mark.asyncio
async def test_title_hint_cannot_bind_a_different_notice_reference():
    from datetime import datetime
    from app.application.workflow import NoticeWorkflow
    from app.search.executor import SearchExecutor
    from app.search.models import SearchResponse, SearchMode, SearchStatus, OrganicResult
    from app.sources import SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation
    original_url='https://issuer.example/notices/a'
    mismatch_url='https://issuer.example/notices/not-a'
    source={
      original_url:b'<main><p>Reference: A/2026</p><p>Issued: 2026-09-01</p><p>Application deadline: 01 October 2026</p></main>',
      mismatch_url:b'<main><h1>Corrigendum</h1><p>Reference: B/2026</p><p>Issued: 2026-09-17</p><p>The deadline is extended from 01 October 2026 to 26 October 2026.</p></main>'}
    class Search:
        def __init__(self): self.queries=[]
        async def search(self, planned, **kwargs):
            self.queries.append(planned.query)
            return SearchResponse(query=planned,mode=SearchMode.SYNTHETIC,status=SearchStatus.OK,
                captured_at=datetime.now(timezone.utc),provider_cached=False,provider_status='Success',
                results=(OrganicResult(link=original_url),OrganicResult(link=mismatch_url)))
    class Transport:
        def get(self,url,max_bytes): return 200,{'content-type':'text/html'},source[url]
    search=Search()
    registry=IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='demo',exact_host='issuer.example',
        verification_evidence_url='https://issuer.example/official',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))
    wf=NoticeWorkflow(executor=SearchExecutor(search),
        fetcher=SafeSourceFetcher(transport=Transport()),registry=registry,evidence_mode='SYNTHETIC_OFFLINE')
    req=NoticeCheckRequest(issuer_id='demo',issuer_name='Demo Issuer',reference_number='A/2026',
        notice_title='Teaching Associates',supplied_deadline=date(2026,10,1),
        original_url=original_url,as_of=datetime(2026,10,8,tzinfo=timezone.utc))
    result=await wf.check(req)
    assert result.analysis.verdict.value == 'UNRESOLVED'
    assert any('"Teaching Associates" corrigendum' in q for q in search.queries)

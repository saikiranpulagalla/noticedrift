"""Independent v0.8 adversarial probes; NO production code is modified."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, date
from hashlib import sha256
from pathlib import Path
import pytest
import fitz
import httpx

from app.sources.models import SourceSnapshot
from app.sources.parse import parse_snapshot
from app.domain.enums import Verdict
from app.search.executor import SearchExecutor
from app.search.cache import LiveSearchCache
from app.search.budget import SharedCreditLedger
from app.search.models import SearchPlan, PlannedQuery, QueryPurpose, QueryTier, SearchResponse, SearchMode, SearchStatus
from app.api.main import create_app, configured_workflow
from app.application.models import CheckOutcome
from app.domain.models import AnalysisResult
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application"))
from test_v07_workflow import workflow, request, ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML


def make_pdf(font_size=10, color=(1,1,1)):
    doc=fitz.open();page=doc.new_page(width=595,height=842)
    for line,y in [
       ('Corrigendum',60),('Reference: A/2026',90),('Issued: 2026-09-17',120),
       ('The deadline is extended from 01 October 2026 to 26 October 2026.',150)]:
        page.insert_text((70,y),line,fontsize=font_size,color=color)
    data=doc.tobytes();doc.close();return data

def make_snapshot(data):
    return SourceSnapshot(source_url=UPDATE,final_url=UPDATE,captured_at=datetime.now(timezone.utc),content_type='application/pdf',body=data,body_sha256=sha256(data).hexdigest())

@pytest.mark.parametrize('fontsize,color', [(10,(1,1,1)), (0.5,(0,0,0))])
def test_pdf_non_perceptible_glyphs_must_not_be_certified_fully_parsed(fontsize,color):
    parsed=parse_snapshot(make_snapshot(make_pdf(fontsize,color)))
    assert parsed.status != 'PARSED', f'Parsed {fontsize}pt {color} PDF as {parsed.status} with warnings={parsed.warning_codes}'

@pytest.mark.asyncio
@pytest.mark.parametrize('attribute', ["style='opacity:0'", "aria-hidden='true'", "style='filter:opacity(0)'", "style='transform:translateX(-10000px)'"])
async def test_invisible_html_variants_never_produce_superseded(attribute):
    html=(f'<main {attribute}><h1>Corrigendum</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p>'
      '<p>The deadline is extended from 01 October 2026 to 26 October 2026.</p></main>').encode()
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:html})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED, f'{attribute}: {out.analysis.verdict}'

@pytest.mark.asyncio
async def test_issuer_host_user_feedback_not_authored_declaration():
    html=b'''<main><h1>Government vacancy information</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p>
      <section class="feedback"><h2>Public submissions</h2>
      <p>The deadline is extended from 01 October 2026 to 26 October 2026.</p></section></main>'''
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:html})
    out=await w.check(request())
    assert out.analysis.verdict != Verdict.SUPERSEDED, out.analysis.verdict

@pytest.mark.asyncio
async def test_cache_singleflight_does_not_double_reserve_credits(tmp_path):
    class SlowClient:
        def __init__(self): self.calls=0
        async def search(self,planned,**params):
            self.calls+=1
            await asyncio.sleep(.08)
            return SearchResponse(query=planned, mode=SearchMode.LIVE, status=SearchStatus.OK,
                captured_at=datetime.now(timezone.utc), provider_cached=False, provider_status='Success')
    client=SlowClient()
    ledger=SharedCreditLedger(tmp_path/'ledger.db',monthly_limit=200)
    executor=SearchExecutor(client,cache=LiveSearchCache(tmp_path/'cache'),ledger=ledger)
    q=PlannedQuery(query='"A/2026"',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    plan=SearchPlan(queries=(q,),max_calls=8)
    await asyncio.gather(*(executor.execute(plan,fresh=False,allow_local_cache=True) for _ in range(4)))
    assert ledger.used()==client.calls, f'ledger used {ledger.used()} but provider dispatched {client.calls} calls'

@pytest.mark.asyncio
async def test_configuration_bad_attestation_fails_closed(monkeypatch,tmp_path):
    manifest=tmp_path/'authority.json'
    manifest.write_text('[{"issuer_id":"abc", "exact_host":"gov.example"}]')
    monkeypatch.setenv('SERPAPI_API_KEY','not-real')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(manifest))
    assert configured_workflow() is None, 'Invalid attestation must return controlled unconfigured response'

@pytest.mark.asyncio
async def test_live_checks_should_not_hold_app_lock_through_all_external_io():
    class SlowWorkflow:
        def __init__(self):self.active=0;self.peak=0
        async def check(self,req,*,fresh=True):
            self.active+=1; self.peak=max(self.peak,self.active)
            await asyncio.sleep(.12)
            self.active-=1
            return CheckOutcome(analysis=AnalysisResult(verdict=Verdict.UNRESOLVED,coverage='INSUFFICIENT',family_id='test',warnings=('TEST',)), execution_mode='NETWORK',provider_calls=0)
    engine=SlowWorkflow()
    app=create_app(engine)
    req=request().model_dump(mode='json')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
        ans=await asyncio.gather(*(client.post('/api/check',json={**req,'supplied_deadline':f'2026-10-{i:02d}'}) for i in (1,2,3)))
    assert engine.peak>1, f'All distinct checks serialized at global API lock: peak={engine.peak}, statuses={[a.status_code for a in ans]}'

@pytest.mark.asyncio
async def test_demo_endpoint_bounded_under_load():
    # The live endpoint has an hourly limiter; the unrestricted demo uses full E2E parsing and snapshots.
    app=create_app(None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
        ans=await asyncio.gather(*(client.post('/api/demo/check',json={'supplied_deadline':'2026-10-01'}) for _ in range(20)))
    assert any(x.status_code==429 for x in ans), f'20 independent demo jobs accepted: {[x.status_code for x in ans]}'

@pytest.mark.asyncio
@pytest.mark.parametrize('fontsize,color', [(10,(1,1,1)), (0.5,(0,0,0))])
async def test_invisible_or_unreadable_pdf_update_cannot_produce_superseded(fontsize,color):
    from app.application.workflow import NoticeWorkflow
    from app.search.executor import SearchExecutor
    from app.sources import SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation
    from test_v07_workflow import FakeTransport, FakeSearch
    update_pdf='https://issuer.example/notices/corrigendum.pdf'
    pdf=make_pdf(fontsize,color)
    class MixedTransport(FakeTransport):
        def get(self,url,max_bytes):
            self.calls.append(url)
            if url == update_pdf:
                return 200, {'content-type':'application/pdf'},pdf
            return 200, {'content-type':'text/html'},self.bodies[url]
    registry=IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='synthetic',exact_host='issuer.example',
       verification_evidence_url='https://directory.example/record',verified_at=datetime.now(timezone.utc),
       verification_method='MANUAL_CROSS_LINK'),))
    w=NoticeWorkflow(executor=SearchExecutor(FakeSearch([ORIGINAL,update_pdf])),
      fetcher=SafeSourceFetcher(transport=MixedTransport({ORIGINAL: ORIG_HTML})),
      registry=registry,evidence_mode='SYNTHETIC_OFFLINE')
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED, f'{fontsize=} {color=} incorrectly gave {out.analysis.verdict}'

@pytest.mark.asyncio
async def test_search_query_must_preserve_nonempty_full_notice_reference():
    from app.application.models import NoticeCheckRequest
    from app.search.planner import plan_queries
    altered_ref='ADV-OR-17/2026'
    plan=plan_queries(reference_number=altered_ref,issuer_name='Synthetic Issuer',title=None,official_domain='issuer.example')
    assert any(altered_ref in x.query for x in plan.queries), [x.query for x in plan.queries]
    # A nonempty but structurally changed ref should not claim complete discovery.
    html=(f'<main><h2>Notice</h2><p>Reference: {altered_ref}</p>'
          '<p>Issued: 2026-09-01</p><p>Application deadline: 01 October 2026</p></main>').encode()
    w,search,_=workflow([],{ORIGINAL:html})
    req=NoticeCheckRequest(issuer_id='synthetic',issuer_name='Synthetic Issuer',reference_number=altered_ref,
        supplied_deadline=date(2026,10,1),as_of=datetime(2026,10,8,tzinfo=timezone.utc),original_url=ORIGINAL)
    out=await w.check(req)
    # Once the reference is preserved, this fixture's search is no longer lossy.
    assert out.analysis.verdict == Verdict.SUPPORTED_BY_EVIDENCE, [q for q,_ in search.calls]

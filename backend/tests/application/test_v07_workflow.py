from __future__ import annotations
from datetime import date,datetime,timezone
import pytest
from app.application.workflow import NoticeWorkflow
from app.application.models import NoticeCheckRequest
from app.domain.enums import Verdict, EvidenceCoverage
from app.search.executor import SearchExecutor
from app.search.models import SearchResponse, SearchStatus, SearchMode, OrganicResult
from app.sources import SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation

ORIGINAL='https://issuer.example/notices/a'
UPDATE='https://issuer.example/notices/a-corrigendum'
UNTRUSTED='https://other.example/notices/a-corrigendum'
ORIG_HTML=b'''<main><h1>Official vacancy notice</h1><p>Reference: A/2026</p><p>Issued: 2026-09-01</p><p>Application deadline: 01 October 2026</p></main>'''
UPDATE_HTML=b'''<main><h1>Corrigendum</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p><p>The deadline is extended from 01 October 2026 to 26 October 2026.</p></main>'''
CANCEL_HTML=b'''<main><h1>Cancellation</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p><p>This recruitment is cancelled.</p></main>'''
UNKNOWN_HTML=b'''<main><h1>Corrigendum</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p><p>The deadline remains unchanged for category A.</p></main>'''
PARTIAL_HTML=b'''<main><h1>Corrigendum</h1><table><tr><td>Deadline</td><td>26 October 2026</td></tr></table><p>Reference: A/2026</p><p>Issued: 2026-09-17</p></main>'''

class FakeTransport:
    def __init__(self,bodies): self.bodies=bodies;self.calls=[]
    def get(self,url,max_bytes):
        self.calls.append(url)
        if url not in self.bodies: raise RuntimeError('not found')
        return 200,{'content-type':'text/html'},self.bodies[url]

class FakeSearch:
    def __init__(self,urls, *, cached=False, failure=False): self.urls=urls;self.calls=[];self.cached=cached;self.failure=failure
    async def search(self,planned,**kw):
        self.calls.append((planned.query,kw))
        return SearchResponse(query=planned,mode=SearchMode.LIVE,
            status=SearchStatus.ERROR if self.failure else SearchStatus.OK,
            captured_at=datetime.now(timezone.utc),provider_cached=self.cached,
            provider_status='Cached' if self.cached else 'Success',
            results=tuple(OrganicResult(link=u,title='result') for u in self.urls))


def workflow(urls,bodies,**kwargs):
    search=FakeSearch(urls,**kwargs)
    transport=FakeTransport(bodies)
    registry=IssuerAuthorityRegistry((AuthorityAttestation(
        issuer_id='synthetic', exact_host='issuer.example',
        verification_evidence_url='https://directory.example/record',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))
    return NoticeWorkflow(executor=SearchExecutor(search),fetcher=SafeSourceFetcher(transport=transport),registry=registry,
                          evidence_mode="SYNTHETIC_OFFLINE"),search,transport

def request(*, deadline=date(2026,10,1), url=None):
    return NoticeCheckRequest(issuer_id='synthetic',issuer_name='Synthetic Issuer',
        reference_number='A/2026',supplied_deadline=deadline,
        as_of=datetime(2026,10,8,tzinfo=timezone.utc),original_url=url)

@pytest.mark.asyncio
async def test_real_modules_end_to_end_superseded():
    w,search,transport=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.SUPERSEDED,out.model_dump()
    assert len(out.sources)==2
    assert out.sources[1].relation_quote.lower().startswith('the deadline is extended')
    assert out.provider_calls <= 8 and out.provider_calls > 0
    assert all(c['no_cache'] is True for _,c in search.calls)
    assert len(transport.calls)==2
    assert out.search_entries and out.sources[1].source_sha256

@pytest.mark.asyncio
async def test_no_change_with_complete_fresh_evidence():
    w,_,_=workflow([ORIGINAL],{ORIGINAL:ORIG_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.SUPPORTED_BY_EVIDENCE,out.model_dump()

@pytest.mark.asyncio
async def test_updated_user_notice_is_supported():
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    out=await w.check(request(deadline=date(2026,10,26)))
    assert out.analysis.verdict == Verdict.SUPPORTED_BY_EVIDENCE,out.model_dump()

@pytest.mark.asyncio
async def test_cancellation():
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:CANCEL_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.CANCELLED,out.model_dump()

@pytest.mark.asyncio
async def test_ambiguous_corrigendum_abstains():
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UNKNOWN_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED
    assert 'POTENTIALLY_GOVERNING_SOURCE_UNRESOLVED' in out.analysis.warnings

@pytest.mark.asyncio
async def test_partial_table_abstains():
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:PARTIAL_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_provider_cache_never_positive():
    w,_,_=workflow([ORIGINAL],{ORIGINAL:ORIG_HTML},cached=True)
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED
    assert 'SEARCH_COVERAGE_INADEQUATE' in out.warnings

@pytest.mark.asyncio
async def test_provider_failure_never_positive():
    w,_,_=workflow([ORIGINAL],{ORIGINAL:ORIG_HTML},failure=True)
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_unknown_host_never_fetched():
    # A material lead identifies this family, not merely a generic corrigendum.
    related = UNTRUSTED + '?reference=A%2F2026'
    w,_,transport=workflow([ORIGINAL,related],{ORIGINAL:ORIG_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED
    assert related not in transport.calls

@pytest.mark.asyncio
async def test_missing_original_abstains():
    w,_,_=workflow([UPDATE],{UPDATE:UPDATE_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_update_wrong_reference_cannot_govern():
    wrong=UPDATE_HTML.replace(b'A/2026',b'B/2026')
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:wrong})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_update_from_date_conflict_abstains():
    wrong=UPDATE_HTML.replace(b'01 October 2026',b'02 October 2026')
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:wrong})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_no_authority_never_spends_search():
    registry=IssuerAuthorityRegistry()
    search=FakeSearch([ORIGINAL]); transport=FakeTransport({ORIGINAL:ORIG_HTML})
    w=NoticeWorkflow(executor=SearchExecutor(search),fetcher=SafeSourceFetcher(transport=transport),registry=registry,
                          evidence_mode="SYNTHETIC_OFFLINE")
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED
    assert not search.calls and not transport.calls

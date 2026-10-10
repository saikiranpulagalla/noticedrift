"""Adversarial expectations for v0.7. These intentionally fail on current production code.
Never modify production code or manufacture success by weakening an expectation.
"""
from datetime import datetime, timezone, date
from hashlib import sha256
import pytest
from app.application.extract import extract_notice, ExtractionUnresolved
from app.application.workflow import MAX_CANDIDATES
from app.domain.enums import Verdict
from app.search.models import OrganicResult
from app.sources.models import ParsedSource
from test_v07_workflow import (
    workflow, request, ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML, CANCEL_HTML
)


def parsed(text):
    return ParsedSource(snapshot_sha256='a'*64, normalized_text_sha256=sha256(text.encode()).hexdigest(), text=text, status='PARSED')


def html_with_payload(sentence):
    return ('<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n' + sentence + '</main>').encode()

@pytest.mark.asyncio
async def test_unknown_update_in_title_and_snippet_must_block_positive_support():
    untrusted = 'https://other.example/read/4837'
    w, _, transport = workflow([ORIGINAL], {ORIGINAL: ORIG_HTML})
    upstream = w.executor.client
    async def search(planned, **kwargs):
        response = await upstream.search(planned, **kwargs)
        return response.model_copy(update={'results': (OrganicResult(link=ORIGINAL, title='Original Notice'),
            OrganicResult(link=untrusted, title='Corrigendum for A/2026',
                         snippet='Official authority extends submission deadline to 26 October 2026'))})
    w.executor.client = type('MetadataSearch', (), {'search': staticmethod(search)})()
    out = await w.check(request())
    assert out.analysis.verdict != Verdict.SUPPORTED_BY_EVIDENCE, out.model_dump()

@pytest.mark.asyncio
async def test_withdrawal_in_same_formal_update_must_not_be_ignored():
    text='The deadline is extended from 01 October 2026 to 26 October 2026. This extension is hereby withdrawn.'
    w,_,_ = workflow([ORIGINAL, UPDATE], {ORIGINAL:ORIG_HTML,UPDATE:html_with_payload(text)})
    out = await w.check(request())
    assert out.analysis.verdict != Verdict.SUPERSEDED, out.model_dump()

@pytest.mark.asyncio
async def test_quote_of_false_cancellation_not_counted_as_cancellation():
    text='A false rumor says: This recruitment is cancelled. This claim is incorrect. The recruitment remains open.'
    w,_,_ = workflow([ORIGINAL, UPDATE], {ORIGINAL:ORIG_HTML,UPDATE:html_with_payload(text)})
    out = await w.check(request())
    assert out.analysis.verdict != Verdict.CANCELLED, out.model_dump()

@pytest.mark.asyncio
async def test_nested_user_comment_must_not_be_formal_corrigendum():
    payload=b'''<main><h1>Corrigendum notice discussion</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p>
       <section class="comments"><h2>Reader comments</h2><p>The deadline is extended from 01 October 2026 to 26 October 2026</p></section></main>'''
    w,_,_ = workflow([ORIGINAL, UPDATE], {ORIGINAL:ORIG_HTML,UPDATE:payload})
    out = await w.check(request())
    assert out.analysis.verdict != Verdict.SUPERSEDED, out.model_dump()

@pytest.mark.asyncio
async def test_root_html_hidden_formal_text_must_not_govern():
    payload=b'''<main hidden><h1>Hidden correction</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p>
       <p>The deadline is extended from 01 October 2026 to 26 October 2026</p></main><article><p>Visible information only.</p></article>'''
    w,_,_ = workflow([ORIGINAL, UPDATE], {ORIGINAL:ORIG_HTML,UPDATE:payload})
    out = await w.check(request())
    assert out.analysis.verdict != Verdict.SUPERSEDED, out.model_dump()

@pytest.mark.asyncio
async def test_extra_irrelevant_results_should_not_erase_proven_change():
    noisy = [f'https://noise.example/irrelevant-{i}' for i in range(MAX_CANDIDATES)]
    w,_,transport = workflow([ORIGINAL, UPDATE, *noisy], {ORIGINAL:ORIG_HTML, UPDATE:UPDATE_HTML})
    out = await w.check(request())
    assert out.analysis.verdict == Verdict.SUPERSEDED, out.model_dump()

@pytest.mark.asyncio
async def test_unrelated_official_result_should_not_block_known_verified_chain():
    unrelated='https://issuer.example/publications/lunch-menu'
    w,_,_ = workflow([ORIGINAL,UPDATE,unrelated], {ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML,
        unrelated:b'<main>Unrelated menu announcement. Here is the cafeteria weekly menu with information.</main>'})
    out = await w.check(request())
    assert out.analysis.verdict == Verdict.SUPERSEDED, out.model_dump()

@pytest.mark.asyncio
async def test_future_asof_positive_verdict_requires_future_evidence_disclaimer():
    w,_,_ = workflow([ORIGINAL], {ORIGINAL:ORIG_HTML})
    future=request().model_copy(update={'as_of': datetime(2099, 1, 1, tzinfo=timezone.utc)})
    out=await w.check(future)
    assert out.analysis.verdict != Verdict.SUPPORTED_BY_EVIDENCE, out.model_dump()


def test_real_nca_f_corrigendum_english_html_is_not_supported_by_exact_parser():
    # Grounded excerpt from official nicf.gov.in 2026-09-17 corrigendum page.
    page = '''Corrigendum of vacancy circular no. 4-22/Estt/Teaching Associates/2026-NCA-F dated 01.09.2026
    In view of the above correction, the last date for the submission of applications for the two (2) posts has been extended.
    The revised deadline for receipt of applications is now 26th October 2026 instead of 1st October 2026.
    All other terms and conditions mentioned in the original advertisement remain unchanged.
    Page Last Updated: 17/09/2026'''
    with pytest.raises(ExtractionUnresolved):
        extract_notice(parsed(page), '4-22/Estt/Teaching Associates/2026-NCA-F')
    # This test documents the capability gap and should PASS; no claim the app supports it.

@pytest.mark.asyncio
async def test_multiple_same_day_sequential_updates_order_independent():
    url2='https://issuer.example/notices/a-second'
    date1='2026-09-17'; date2='2026-09-17'
    # Inject harmless source variations to vary content hash (currently used as tie-breaker).
    for suffix in ('10',):
        first=UPDATE_HTML+b'<!-- '+suffix.encode()+b' -->'
        second=b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\nThe deadline is extended from 26 October 2026 to 30 October 2026</main>'
        w,_,_=workflow([ORIGINAL,UPDATE,url2], {ORIGINAL:ORIG_HTML,UPDATE:first,url2:second})
        out=await w.check(request())
        assert out.analysis.verdict == Verdict.SUPERSEDED, (suffix,out.analysis.verdict, out.model_dump())

@pytest.mark.asyncio
async def test_same_bytes_under_two_official_urls_should_not_create_two_originals():
    mirror='https://issuer.example/mirror/a'
    w,_,_=workflow([ORIGINAL,UPDATE,mirror],{ORIGINAL:ORIG_HTML, UPDATE:UPDATE_HTML,mirror:ORIG_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.SUPERSEDED, out.model_dump()

@pytest.mark.asyncio
async def test_hidden_css_class_cannot_supply_formal_update():
    payload=b'''<main><h1>Corrigendum</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p>
       <style>.invisible { display:none }</style>
       <p class="invisible">The deadline is extended from 01 October 2026 to 26 October 2026</p>
       <p>Applications remain open under the original notice.</p></main>'''
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:payload})
    out=await w.check(request())
    assert out.analysis.verdict != Verdict.SUPERSEDED, out.model_dump()

@pytest.mark.asyncio
async def test_many_external_queries_can_exhaust_live_credits_without_api_throttle():
    import httpx, asyncio
    from app.api.main import create_app
    w,search,_ = workflow([ORIGINAL],{ORIGINAL:ORIG_HTML})
    app=create_app(w)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        answers=await asyncio.gather(*(client.post('/api/check',json=request().model_dump(mode='json')) for _ in range(9)))
    assert all(r.status_code==200 for r in answers)
    assert len(search.calls) <= 8, f'9 requests caused {len(search.calls)} provider searches despite per-run cap'

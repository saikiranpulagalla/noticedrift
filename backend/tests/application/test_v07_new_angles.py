"""Adversarial contracts for v0.7. Additive tests: do not edit production code.
Failures are expected against the released v0.7 archive.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import sleep

import fitz
import pytest
from app.application.workflow import NoticeWorkflow
from app.application.models import NoticeCheckRequest
from app.api.main import configured_workflow
from app.domain.enums import Verdict
from app.search.executor import SearchExecutor
from app.sources import SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation
from app.sources.models import SourceSnapshot
from app.sources.parse import parse_snapshot
from test_v07_workflow import (
    workflow, request, ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML, FakeSearch, FakeTransport,
)

PDF_UPDATE='https://issuer.example/notices/correction.pdf'

def pdf_with_invisible_update(kind):
    doc=fitz.open(); page=doc.new_page(width=595,height=842)
    for line,y in [
        ('Corrigendum',60),
        ('Reference: A/2026',90),
        ('Issued: 2026-09-17',120),
        ('The deadline is extended from 01 October 2026 to 26 October 2026.',150),
    ]:
        page.insert_text((70,y),line,fontsize=10,
                         render_mode=3 if kind=='invisible_render_mode' else 0)
    if kind=='opaque_overlay':
        page.draw_rect(fitz.Rect(60,65,550,165),color=(1,1,1),fill=(1,1,1),overlay=True)
    content=doc.tobytes();doc.close();return content

@pytest.mark.parametrize('kind',['invisible_render_mode','opaque_overlay'])
def test_pdf_visual_evidence_must_not_be_marked_fully_trustworthy(kind):
    content=pdf_with_invisible_update(kind)
    snapshot=SourceSnapshot(
        source_url=PDF_UPDATE, final_url=PDF_UPDATE,content_type='application/pdf',
        body=content,body_sha256=sha256(content).hexdigest(),captured_at=datetime.now(timezone.utc))
    parsed=parse_snapshot(snapshot)
    assert parsed.status != 'PARSED',f'Invisible/occluded PDF correction wrongly marked PARSED: {kind}'

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['invisible_render_mode','opaque_overlay'])
async def test_hidden_pdf_corrigendum_must_not_create_definitive_supersession(kind):
    class MixedTransport(FakeTransport):
        def get(self,url,max_bytes):
            self.calls.append(url)
            if url==PDF_UPDATE:
                return 200,{'content-type':'application/pdf'},pdf_with_invisible_update(kind)
            return 200,{'content-type':'text/html'},self.bodies[url]
    search=FakeSearch([ORIGINAL,PDF_UPDATE])
    registry=IssuerAuthorityRegistry((AuthorityAttestation(
        issuer_id='synthetic',exact_host='issuer.example',
        verification_evidence_url='https://directory.example/record',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))
    w=NoticeWorkflow(executor=SearchExecutor(search),
        fetcher=SafeSourceFetcher(transport=MixedTransport({ORIGINAL:ORIG_HTML})),
        registry=registry,evidence_mode='SYNTHETIC_OFFLINE')
    out=await w.check(request())
    assert out.analysis.verdict==Verdict.UNRESOLVED, f'Invisible PDF caused {out.analysis.verdict}'

@pytest.mark.asyncio
async def test_unattested_intermediate_redirect_must_not_be_fetched():
    """A redirect may end on approved host after visiting unrelated external host."""
    start='https://issuer.example/start'
    third='https://tracker.external.example/click'
    class RedirectTransport:
        def __init__(self): self.calls=[]
        def get(self,url,max_bytes):
            self.calls.append(url)
            if url==start: return 302,{'location':third},b''
            if url==third: return 302,{'location':ORIGINAL},b''
            if url==ORIGINAL: return 200,{'content-type':'text/html'},ORIG_HTML
            raise AssertionError(url)
    registry=IssuerAuthorityRegistry((AuthorityAttestation(
        issuer_id='synthetic',exact_host='issuer.example',
        verification_evidence_url='https://directory.example/record',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))
    transport=RedirectTransport()
    w=NoticeWorkflow(executor=SearchExecutor(FakeSearch([start])),
                     fetcher=SafeSourceFetcher(transport=transport),registry=registry,
                     evidence_mode='SYNTHETIC_OFFLINE')
    out=await w.check(request())
    assert third not in transport.calls, f'Fetched unapproved hop {third}; verdict={out.analysis.verdict}'

@pytest.mark.asyncio
async def test_operator_manifest_attestation_from_future_must_not_govern():
    attestation=AuthorityAttestation(issuer_id='synthetic',exact_host='issuer.example',
        verification_evidence_url='https://directory.example/record',
        verified_at=datetime(2099,1,1,tzinfo=timezone.utc),verification_method='MANUAL_CROSS_LINK')
    registry=IssuerAuthorityRegistry((attestation,))
    w=NoticeWorkflow(executor=SearchExecutor(FakeSearch([ORIGINAL])),
        fetcher=SafeSourceFetcher(transport=FakeTransport({ORIGINAL:ORIG_HTML})),
        registry=registry,evidence_mode='SYNTHETIC_OFFLINE')
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED,'Future-verified issuer attestation accepted'

@pytest.mark.asyncio
async def test_degenerate_reference_must_not_yield_adequate_search_assurance():
    """Operator-like reference words removed as Google operators -> broad searches."""
    html=b'<main><p>Reference: OR</p><p>Issued: 2026-09-01</p><p>Application deadline: 01 October 2026</p></main>'
    w,search,_=workflow([],{ORIGINAL:html})
    req=NoticeCheckRequest(issuer_id='synthetic',issuer_name='Synthetic Issuer',
            reference_number='OR', supplied_deadline=date(2026,10,1),
            as_of=datetime(2026,10,8,tzinfo=timezone.utc),original_url=ORIGINAL)
    out=await w.check(req)
    assert out.analysis.verdict == Verdict.UNRESOLVED, f'Generic queries incorrectly certified current; queries={[q for q,_ in search.calls]}'

@pytest.mark.asyncio
async def test_all_approved_issuer_hosts_must_participate_in_update_coverage():
    entries=tuple(AuthorityAttestation(issuer_id='synthetic',exact_host=host,
        verification_evidence_url='https://directory.example/record',
        verified_at=datetime(2026,9,1,tzinfo=timezone.utc),
        verification_method='MANUAL_CROSS_LINK')
        for host in ('a.issuer.example','b.issuer.example'))
    reg=IssuerAuthorityRegistry(entries)
    orig='https://a.issuer.example/notices/a'
    client=FakeSearch([orig])
    w=NoticeWorkflow(executor=SearchExecutor(client),
        fetcher=SafeSourceFetcher(transport=FakeTransport({orig:ORIG_HTML})),
        registry=reg,evidence_mode='SYNTHETIC_OFFLINE')
    out=await w.check(request())
    requested=' '.join(q for q,_ in client.calls)
    assert 'site:b.issuer.example' in requested or out.analysis.verdict == Verdict.UNRESOLVED, (
        f'Only site:a was explicitly searched although issuer has two attested hosts; verdict={out.analysis.verdict}')

@pytest.mark.asyncio
async def test_source_capture_must_be_replayable_from_result():
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    out=await w.check(request())
    assert out.analysis.verdict==Verdict.SUPERSEDED
    # Search metadata and hashes cannot reproduce exact original source bytes.
    assert all(hasattr(source,'snapshot_id') and getattr(source,'snapshot_id') for source in out.sources), (
        'SourceTrace contains hashes but no storage-backed snapshot reference; exact source cannot be replayed')

@pytest.mark.asyncio
async def test_cancelled_fetch_thread_must_not_keep_doing_work():
    """Time out the async request while a worker performs a blocking source fetch."""
    import threading
    started=threading.Event(); finished=threading.Event()
    class SlowTransport:
        def get(self,url,max_bytes):
            started.set()
            sleep(0.18)
            finished.set()
            return 200,{'content-type':'text/html'},ORIG_HTML
    reg=IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='synthetic',exact_host='issuer.example',
        verification_evidence_url='https://directory.example/record',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))
    w=NoticeWorkflow(executor=SearchExecutor(FakeSearch([ORIGINAL])),
       fetcher=SafeSourceFetcher(transport=SlowTransport()),registry=reg,evidence_mode='SYNTHETIC_OFFLINE')
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(w.check(request()),timeout=0.08)
    assert started.is_set()
    assert finished.is_set(),'Underlying blocking fetch continued after request was cancelled'


def test_invalid_operator_manifest_must_fail_as_unconfigured_not_crash(monkeypatch,tmp_path):
    manifest=tmp_path/'issuer-attestations.json'
    manifest.write_text('{bad json')
    monkeypatch.setenv('SERPAPI_API_KEY','synthetic-not-real')
    monkeypatch.setenv('NOTICEDRIFT_ISSUER_ATTESTATIONS',str(manifest))
    assert configured_workflow() is None

@pytest.mark.asyncio
async def test_date_only_issuance_cannot_establish_intraday_historical_state():
    """'Issued: 2026-09-17' does not prove publication by 00:05 UTC that day."""
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    req=NoticeCheckRequest(issuer_id='synthetic',issuer_name='Synthetic Issuer',
            reference_number='A/2026',supplied_deadline=date(2026,10,1),
            as_of=datetime(2026,9,17,0,5,tzinfo=timezone.utc))
    out=await w.check(req)
    assert out.analysis.verdict==Verdict.UNRESOLVED, (
      'A date-only issuance was interpreted as 00:00 UTC and applied to a 00:05 UTC historical check')

@pytest.mark.asyncio
async def test_unreadable_official_source_is_identified_in_evidence_trace():
    """Output must identify which exact result blocked the verdict, not just generic status."""
    bad=b'<main><h1>Unknown corrigendum</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p><p>Deadline may be changed; contact staff.</p></main>'
    w,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:bad})
    out=await w.check(request())
    assert out.analysis.verdict==Verdict.UNRESOLVED
    all_explanations=' '.join((*out.warnings,*(x.url for x in out.sources)))
    assert UPDATE in all_explanations, (
        'A potentially governing official source blocked the verdict without its URL or failure reason in the trace')

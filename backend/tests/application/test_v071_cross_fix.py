"""Cross-fix release invariants: prove one repair cannot reopen another."""
from datetime import date, datetime, timezone
from hashlib import sha256
import fitz
import pytest
from app.domain.enums import Verdict
from app.sources.models import SourceSnapshot
from app.sources.parse import parse_snapshot
from test_v07_workflow import ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML, workflow, request

@pytest.mark.asyncio
async def test_causal_same_day_chain_with_parent_predating_child_remains_supported():
    url = 'https://issuer.example/second'
    second = (b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n'
              b'The deadline is extended from 26 October 2026 to 30 October 2026</main>')
    w,_,_ = workflow([ORIGINAL,UPDATE,url],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML,url:second})
    out = await w.check(request())
    assert out.analysis.verdict == Verdict.SUPERSEDED
    assert out.analysis.field_resolutions[0].value == date(2026,10,30)

@pytest.mark.asyncio
async def test_value_chain_cannot_amend_a_document_issued_in_the_future():
    url = 'https://issuer.example/second'
    first = UPDATE_HTML.replace(b'2026-09-17',b'2026-09-20')
    second = (b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n'
              b'The deadline is extended from 26 October 2026 to 30 October 2026</main>')
    w,_,_ = workflow([ORIGINAL,UPDATE,url],{ORIGINAL:ORIG_HTML, UPDATE:first,url:second})
    out = await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_evidence_snapshot_is_retrievable_and_unchanged():
    w,_,_ = workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    out=await w.check(request())
    assert out.analysis.verdict == Verdict.SUPERSEDED
    originals = [s for s in out.sources if s.role == 'ORIGINAL_NOTICE']
    assert len(originals)==1
    captured = w.snapshot_store.get(originals[0].snapshot_id)
    assert captured.body == ORIG_HTML
    assert captured.body_sha256 == originals[0].source_sha256

@pytest.mark.asyncio
async def test_future_asof_rejected_before_spending_any_search():
    w,search,transport = workflow([ORIGINAL],{ORIGINAL:ORIG_HTML})
    future = request().model_copy(update={'as_of':datetime(2099,1,1,tzinfo=timezone.utc)})
    out = await w.check(future)
    assert out.analysis.verdict == Verdict.UNRESOLVED
    assert search.calls == [] and transport.calls == []

@pytest.mark.asyncio
async def test_style_selector_with_uncertain_visibility_blocks_decisive_quotation():
    evil = (b'<main><h1>Corrigendum</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p>'
            b'<style>main p:nth-child(4) { display: none }</style>'
            b'<p>The deadline is extended from 01 October 2026 to 26 October 2026</p></main>')
    w,_,_ = workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:evil})
    out = await w.check(request())
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_comment_text_not_governing_even_if_it_declares_cancellation():
    evil=(b'<main><h1>Notice discussion</h1><p>Reference: A/2026</p><p>Issued: 2026-09-17</p>'
          b'<section class="comments"><p>This recruitment is cancelled.</p></section>'
          b'<p>Original deadline continues.</p></main>')
    w,_,_ = workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:evil})
    out=await w.check(request())
    assert out.analysis.verdict != Verdict.CANCELLED

def test_plain_visible_pdf_text_remains_supported():
    doc=fitz.open(); page=doc.new_page()
    page.insert_text((55,80),'Reference: A/2026')
    page.insert_text((55,100),'Issued: 2026-09-17')
    page.insert_text((55,120),'The deadline is extended from 01 October 2026 to 26 October 2026')
    body=doc.tobytes();doc.close()
    snapshot=SourceSnapshot(source_url='https://issuer.example/a.pdf',final_url='https://issuer.example/a.pdf',
          captured_at=datetime.now(timezone.utc),content_type='application/pdf',body=body,
          body_sha256=sha256(body).hexdigest())
    parsed=parse_snapshot(snapshot)
    assert parsed.status == 'PARSED',parsed.warning_codes

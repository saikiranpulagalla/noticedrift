from __future__ import annotations
from datetime import datetime, timezone, date
from hashlib import sha256
import pytest
import fitz
from app.sources import (SourceSnapshot, SourceFailure, SourceErrorCode, AuthorityAttestation,
                         IssuerAuthorityRegistry, parse_snapshot, ground_exact_quote,
                         admit_document, verify_span, SnapshotStore)
from app.domain.models import NoticeIdentity
from app.domain.enums import CriticalField, DocumentRole, SourceClass, ParserStatus


def snap(body, media='text/html', url='https://issuer.example/a'):
    return SourceSnapshot(source_url=url,final_url=url,captured_at=datetime.now(timezone.utc),
                          content_type=media,body=body,body_sha256=sha256(body).hexdigest())


def registry():
    return IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='agency-A', exact_host='issuer.example',
            verification_evidence_url='https://directory.example/issuers/agency-A',
            verification_method='MANUAL_OFFICIAL_DIRECTORY',
            verified_at=datetime.now(timezone.utc)),))


def identity():
    return NoticeIdentity(issuer_id='agency-A', reference_numbers=('A/2026',), title='Teaching Associates')


def test_html_script_stripped_and_exact_quote():
    s = snap(b'<html><body><nav>About</nav><main><script>evil()</script><p>Corrigendum</p><p>Deadline extended to 26 October 2026</p></main></body></html>')
    p = parse_snapshot(s)
    assert p.status == 'PARSED'
    assert 'evil' not in p.text and 'About' not in p.text
    quote = '26 October 2026'
    evidence = ground_exact_quote(s,p,quote)
    assert verify_span(p,evidence,s)
    attested = admit_document(s,p,identity(),'doc-ext',DocumentRole.CORRIGENDUM,registry(),grounded_fields=(
        (CriticalField.DEADLINE, quote, date(2026,10,26), evidence),))
    assert attested.source_class == SourceClass.ISSUER_PRIMARY
    assert attested.parser_status == ParserStatus.PARSED
    assert attested.fields[0].source_document_id == 'doc-ext'


def test_no_gov_suffix_magic_and_redirect_authority_tied_to_final_host():
    s = snap(b'<main><p>Corrigendum. Deadline extended to 26 October 2026.</p></main>',
             url='https://evil.gov.in/notice')
    p = parse_snapshot(s)
    doc = admit_document(s,p,identity(),'doc',DocumentRole.CORRIGENDUM,registry())
    assert doc.source_class == SourceClass.UNKNOWN


def test_malformed_role_fails_closed():
    s = snap(b'<main>Notice about a campus event and deadline 26 October 2026.</main>')
    p = parse_snapshot(s)
    with pytest.raises(SourceFailure):
        admit_document(s,p,identity(),'doc',DocumentRole.CANCELLATION,registry())


def test_forged_normalized_date_refused():
    s = snap(b'<main><p>Corrigendum: Deadline extended to 26 October 2026</p></main>')
    p = parse_snapshot(s)
    span = ground_exact_quote(s,p,'26 October 2026')
    with pytest.raises(SourceFailure) as exc:
        admit_document(s,p,identity(),'d',DocumentRole.CORRIGENDUM,registry(),grounded_fields=((
            CriticalField.DEADLINE,'26 October 2026',date(2026,10,30),span),))
    assert exc.value.code == SourceErrorCode.UNGROUNDED_ASSERTION


def test_forged_quotation_rejected():
    s = snap(b'<main><p>Corrigendum: Deadline extended to 26 October 2026</p></main>')
    p = parse_snapshot(s)
    from app.sources.models import EvidenceSpan
    forged = EvidenceSpan(snapshot_sha256=s.body_sha256, text_sha256=p.normalized_text_sha256,
                          start=0,end=3,quotation='BAD')
    assert not verify_span(p,forged,s)
    with pytest.raises(SourceFailure):
        admit_document(s,p,identity(),'d',DocumentRole.CORRIGENDUM,registry(),grounded_fields=((
            CriticalField.DEADLINE,'BAD',date(2026,10,26),forged),))


def test_repeated_quotes_must_use_offsets():
    s = snap(b'<main>Deadline 26 October 2026. Deadline 26 October 2026.</main>')
    p = parse_snapshot(s)
    with pytest.raises(SourceFailure):
        ground_exact_quote(s,p,'26 October 2026')
    idx = p.text.find('26 October 2026')
    assert ground_exact_quote(s,p,'26 October 2026',start=idx).start == idx


def test_html_table_is_partial_and_cannot_be_admitted_as_decisive():
    s = snap(b'<main><table><tr><th>Post</th><th>Deadline</th></tr>'
             b'<tr><td>A</td><td>10 October 2026</td></tr></table></main>')
    p = parse_snapshot(s)
    assert p.status == 'PARTIAL'
    assert 'HTML_TABLE_STRUCTURE_UNVERIFIED' in p.warning_codes
    with pytest.raises(SourceFailure):
        ground_exact_quote(s,p,'10 October 2026')


def test_text_only_and_unknown_encoding():
    s = snap(b'Corrigendum\nDeadline extended to 26 October 2026','text/plain')
    assert parse_snapshot(s).status == 'PARSED'
    assert parse_snapshot(snap(b'\xff\xfe\x80','text/plain')).status == 'UNSUPPORTED'


def test_html_without_content_abstains():
    s = snap(b'<html><script>render()</script><main></main></html>')
    assert parse_snapshot(s).status == 'UNSUPPORTED'


def make_pdf(*, text=None, image=False):
    doc = fitz.open(); page=doc.new_page()
    if text:
        page.insert_text((30,30), text)
    if image:
        from PIL import Image
        import io
        img = Image.new('RGB',(15,15), 'white'); f=io.BytesIO(); img.save(f,format='PNG')
        page.insert_image(fitz.Rect(40,40,80,80),stream=f.getvalue())
    data = doc.tobytes(); doc.close(); return data


def test_pdf_text_and_page_grounding():
    s = snap(make_pdf(text='Corrigendum deadline 26 October 2026'),'application/pdf')
    p = parse_snapshot(s)
    assert p.status == 'PARSED' and len(p.pages) == 1
    evidence = ground_exact_quote(s,p,'26 October 2026')
    assert evidence.page_number == 1
    assert verify_span(p,evidence,s)


def test_scanned_pdf_and_corruption_abstain():
    s = snap(make_pdf(image=True),'application/pdf')
    assert parse_snapshot(s).status == 'UNSUPPORTED'
    s2 = snap(b'%PDF-1.7 nonsense','application/pdf')
    assert parse_snapshot(s2).status == 'FAILED'


def test_pdf_image_containing_text_marks_partial():
    s = snap(make_pdf(text='Corrigendum deadline 26 October 2026',image=True),'application/pdf')
    p = parse_snapshot(s)
    assert p.status == 'PARTIAL'
    assert 'PDF_HAS_IMAGES' in p.warning_codes


def test_snapshot_store_roundtrip_binary_and_tamper(tmp_path):
    store = SnapshotStore(tmp_path/'snapshots')
    s = snap(make_pdf(text='deadline 26 October 2026'),'application/pdf')
    digest = store.put(s)
    assert store.get(digest).body == s.body
    p = tmp_path/'snapshots'/(digest+'.json')
    p.write_text(p.read_text().replace('26', '30'))  # May not appear in encoded data; tamper metadata instead.
    import json
    record = json.loads(p.read_text()); record['source_url'] = 'https://evil.example/'
    p.write_text(json.dumps(record))
    with pytest.raises(SourceFailure):
        store.get(digest)


def test_snapshot_store_rejects_bad_digest_or_corrupt_data(tmp_path):
    store = SnapshotStore(tmp_path)
    with pytest.raises(SourceFailure):
        store.get('../evil')
    digest = 'f'*64; (tmp_path/(digest+'.json')).write_text('{bad json')
    with pytest.raises(SourceFailure):
        store.get(digest)


def test_authority_registry_requires_manual_evidence():
    with pytest.raises(ValueError):
        IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='agency-A',exact_host='issuer.example',
          verification_evidence_url='http://a.test', verified_at=datetime.now(timezone.utc),
          verification_method='MANUAL_CROSS_LINK'),))
    assert not registry().verified('agency-A','https://issuer.example.evil.test/')
    assert not registry().verified('agency-B','https://issuer.example/')

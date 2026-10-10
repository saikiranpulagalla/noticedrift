"""Branch-focused adversaries for v0.6 trust boundaries; no external network calls."""
from __future__ import annotations
import base64
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import socket
import pytest
import fitz
from app.sources import *
from app.sources.values import grounded_canonical
from app.domain.enums import CriticalField, DocumentRole
from app.domain.models import NoticeIdentity
from app.domain.value_semantics import canonical_value


def snap(body=b'<main>Corrigendum: Deadline extended to 26 October 2026</main>',media='text/html'):
    return SourceSnapshot(body=body,body_sha256=sha256(body).hexdigest(),
        captured_at=datetime.now(timezone.utc),content_type=media,
        source_url='https://issuer.example/a',final_url='https://issuer.example/a')


def registry():
    return IssuerAuthorityRegistry((AuthorityAttestation(
        issuer_id='issuer',exact_host='issuer.example',
        verification_evidence_url='https://directory.example/issuer',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))


def identity():
    return NoticeIdentity(issuer_id='issuer', title='Notice',reference_numbers=('N-2026',))


@pytest.mark.parametrize('field,raw,expected', [
    (CriticalField.DEADLINE,'2026-10-26',('deadline_date','2026-10-26')),
    (CriticalField.DEADLINE,'26 Oct 2026',('deadline_date','2026-10-26')),
    (CriticalField.DEADLINE,'October 26, 2026',('deadline_date','2026-10-26')),
    (CriticalField.DEADLINE,'Oct 26, 2026',('deadline_date','2026-10-26')),
    (CriticalField.FEE,'₹ 100',('money','INR',canonical_value(CriticalField.FEE,'INR 100')[2])),
    (CriticalField.REWARD,'USD 100',canonical_value(CriticalField.REWARD,'USD 100')),
    (CriticalField.APPLICATION_URL,'https://example.com/#/apply',canonical_value(CriticalField.APPLICATION_URL,'https://example.com/#/apply')),
    (CriticalField.TEAM_SIZE,'5',canonical_value(CriticalField.TEAM_SIZE,5)),
    (CriticalField.MIN_AGE,'18',canonical_value(CriticalField.MIN_AGE,18)),
    (CriticalField.LOCATION_MODE,'Online',canonical_value(CriticalField.LOCATION_MODE,'Online')),
    (CriticalField.RESIDENCY,'India',canonical_value(CriticalField.RESIDENCY,'India')),
])
def test_grounded_values(field,raw,expected):
    assert grounded_canonical(field,raw) == expected


@pytest.mark.parametrize('field,raw', [
    (CriticalField.DEADLINE,'05/06/26'),
    (CriticalField.DEADLINE,'Oct 26'),
    (CriticalField.FEE,'100'),
    (CriticalField.FEE,'up to INR 100'),
    (CriticalField.FEE,'₹ 3 lakh+'),
    (CriticalField.APPLICATION_URL,'javascript:alert(1)'),
    (CriticalField.TEAM_SIZE,'18 years'),
    (CriticalField.MIN_AGE,'-1'),
])
def test_unsupported_grounded_values_abstain(field,raw):
    with pytest.raises(SourceFailure) as e:
        grounded_canonical(field,raw)
    assert e.value.code == SourceErrorCode.UNGROUNDED_ASSERTION


def test_unbacked_field_semantics_abstain():
    with pytest.raises(SourceFailure):
        grounded_canonical(CriticalField('deadline'), 'not a date')


def test_source_snapshot_invalid_metadata_and_integrity():
    s = snap()
    with pytest.raises(ValueError):
        SourceSnapshot.model_validate({**s.model_dump(),'captured_at':datetime(2026,10,1)})
    with pytest.raises(ValueError):
        SourceSnapshot.model_validate({**s.model_dump(),'body':b'tampered'})
    with pytest.raises(ValueError):
        ParsedSource(snapshot_sha256=s.body_sha256,normalized_text_sha256='0'*64,
                     text='not blank',status='PARSED')
    text='hello'
    with pytest.raises(ValueError):
        ParsedSource(snapshot_sha256=s.body_sha256,normalized_text_sha256=sha256(text.encode()).hexdigest(),
                     text=text,status='PARSED',pages=((1,0,99),))


def test_span_integrity_challenge_matrix():
    s=snap(); p=parse_snapshot(s)
    actual=ground_exact_quote(s,p,'26 October 2026')
    alterations=[
        {'snapshot_sha256':'f'*64},
        {'text_sha256':'f'*64},
        {'start':-1},
        {'end':len(p.text)+1},
        {'quotation':'NOT REAL'},
        {'page_number':1},
        {'end':actual.start},
    ]
    for change in alterations:
        attempt=actual.model_copy(update=change)
        assert not verify_span(p,attempt,s), change
    forged_snap=s.model_copy(update={'body_sha256':'f'*64})
    assert not verify_span(p,actual,forged_snap)
    with pytest.raises(SourceFailure):
        ground_exact_quote(s,p,'never seen')
    with pytest.raises(SourceFailure):
        ground_exact_quote(s,p,'x'*3001)
    with pytest.raises(SourceFailure):
        ground_exact_quote(s,p,'')
    with pytest.raises(SourceFailure):
        ground_exact_quote(s,p,'26 October 2026',start=0)


def test_attestation_bad_hosts_and_methods():
    now=datetime.now(timezone.utc)
    base=dict(issuer_id='issuer', exact_host='issuer.example',
              verification_evidence_url='https://directory.example/doc',
              verified_at=now, verification_method='MANUAL_CROSS_LINK')
    for change in ({'exact_host':'issuer.example/foo'}, {'exact_host':'ISSUER.EXAMPLE'},
                   {'verification_method':'GOOGLE_TOP_RESULT'},
                   {'verification_evidence_url':'file:///etc/passwd'}):
        entry=AuthorityAttestation(**{**base,**change})
        with pytest.raises(ValueError):
            IssuerAuthorityRegistry((entry,))
    good=AuthorityAttestation(**base)
    with pytest.raises(ValueError):
        IssuerAuthorityRegistry((good,good))
    with pytest.raises(ValueError):
        AuthorityAttestation(**{**base,'verified_at':datetime(2026,10,1)})
    r=registry()
    assert r.approved_hosts('issuer') == frozenset({'issuer.example'})
    assert r.approved_hosts('unknown') == frozenset()
    assert not r.verified('issuer','http://issuer.example/a')
    assert not r.verified('issuer','https://evil.example/a')


def test_admit_provenance_and_decisive_assertions():
    s=snap(); p=parse_snapshot(s)
    quote=ground_exact_quote(s,p,'26 October 2026')
    with pytest.raises(SourceFailure):
        admit_document(s,p,identity(),'d',DocumentRole.CORRIGENDUM,registry(),grounded_fields=((
            CriticalField.DEADLINE,'wrong raw',date(2026,10,26),quote),))
    wrong=s.model_copy(update={'body_sha256':'f'*64})
    with pytest.raises(SourceFailure):
        admit_document(wrong,p,identity(),'d',DocumentRole.CORRIGENDUM,registry())
    altered=p.model_copy(update={'normalized_text_sha256':'f'*64})
    with pytest.raises(SourceFailure):
        admit_document(s,altered,identity(),'d',DocumentRole.CORRIGENDUM,registry())
    with pytest.raises(SourceFailure):
        admit_document(s,p,identity(),'d',DocumentRole.CORRIGENDUM,registry(),grounded_fields=((
            CriticalField.FEE,'26 October 2026',26,quote),))


def test_html_partial_truncation_hidden_and_javascript():
    raw=b'<html><body><main><div hidden="hidden">Secret text</div><span style="display:none">Hidden 2</span><p>Corrigendum: '+b'a'*200_001+b'</p></main></body></html>'
    parsed=parse_snapshot(snap(raw))
    assert parsed.status == 'PARTIAL'
    assert 'TEXT_TRUNCATED' in parsed.warning_codes
    assert 'Secret text' not in parsed.text and 'Hidden 2' not in parsed.text


def test_html_comment_and_hidden_visibility():
    p=parse_snapshot(snap(b'<main><!-- COMMENT --><p style="visibility:hidden">Secret</p><p>Official notice with full visible terms.</p></main>'))
    assert p.status == 'PARSED'
    assert 'COMMENT' not in p.text and 'Secret' not in p.text


def test_html_table_excludes_evidence_only_in_partial():
    p=parse_snapshot(snap(b'<main><p>Official notice</p><table><tr><td>Deadline</td><td>October 26</td></tr></table></main>'))
    assert p.status == 'PARTIAL'


def test_pdf_multi_page_and_page_limit(monkeypatch):
    d=fitz.open(); d.new_page().insert_text((40,40),'Original deadline 01 October 2026')
    d.new_page().insert_text((40,40),'Corrigendum deadline 26 October 2026')
    body=d.tobytes(); d.close()
    s=snap(body,'application/pdf'); p=parse_snapshot(s)
    assert len(p.pages)==2
    q=ground_exact_quote(s,p,'26 October 2026')
    assert q.page_number==2
    forged=q.model_copy(update={'page_number':1})
    assert not verify_span(p,forged,s)
    monkeypatch.setattr('app.sources.parse.MAX_PDF_PAGES',1)
    p2=parse_snapshot(s)
    assert p2.status=='PARTIAL' and 'PDF_PAGE_LIMIT' in p2.warning_codes


def test_pdf_password_protected_and_empty():
    d=fitz.open(); d.new_page().insert_text((40,40),'Secret 26 October 2026')
    data=d.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='user'); d.close()
    p=parse_snapshot(snap(data,'application/pdf'))
    assert p.status=='UNSUPPORTED' and 'ENCRYPTED_PDF' in p.warning_codes


def test_pdf_length_budget(monkeypatch):
    d=fitz.open(); d.new_page().insert_text((40,40),'Long 26 October 2026')
    s=snap(d.tobytes(),'application/pdf');d.close()
    monkeypatch.setattr('app.sources.parse.MAX_TEXT_CHARS',5)
    p=parse_snapshot(s)
    assert p.status == 'UNSUPPORTED' or p.status == 'PARTIAL'
    assert 'TEXT_TRUNCATED' in p.warning_codes or 'SCANNED_OR_EMPTY_PDF' in p.warning_codes


def test_parse_unrecognized_media_and_parser_fault(monkeypatch):
    with pytest.raises(SourceFailure):
        parse_snapshot(snap(media='image/gif'))
    from app.sources import parse as module
    monkeypatch.setattr(module, '_parse_text',lambda _: 1/0)
    assert parse_snapshot(snap()).status=='FAILED'


def test_invalid_pdf_and_image_pdf():
    assert parse_snapshot(snap(b'%PDF-not-valid', 'application/pdf')).status=='FAILED'


class FakeTransport:
    def __init__(self,responses): self.responses=list(responses)
    def get(self,url,max_bytes): return self.responses.pop(0)


def test_fetch_structural_errors_and_limits():
    with pytest.raises(SourceFailure) as e:
        SafeSourceFetcher(FakeTransport([(301,{},b'')])).fetch('https://issuer.example/a')
    assert e.value.code==SourceErrorCode.HTTP_ERROR
    with pytest.raises(SourceFailure) as e:
        SafeSourceFetcher(FakeTransport([(302,{'location':'http://issuer.example/a'},b'')])).fetch('https://issuer.example/a')
    assert e.value.code==SourceErrorCode.UNSAFE_URL
    # Fake transport bypasses network framing; the actual pinned transport is tested separately.


def test_fetch_content_length_pinned(monkeypatch):
    client,server=socket.socketpair()
    server.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 900000\r\nContent-Type: text/html\r\n\r\n')
    monkeypatch.setattr(socket,'create_connection',lambda address,timeout: client)
    def resolver(host,port,type): return [(None,None,None,None,('8.8.8.8',port))]
    with pytest.raises(SourceFailure) as e:
        PinnedHTTPTransport(resolve=resolver).get('http://issuer.example/a',10)
    assert e.value.code==SourceErrorCode.OVERSIZED
    server.close()


def test_pinned_transport_network_failure():
    def resolver(host,port,type): return [(None,None,None,None,('8.8.8.8',port))]
    transport=PinnedHTTPTransport(resolve=resolver)
    import unittest.mock
    with unittest.mock.patch('socket.create_connection',side_effect=OSError('network')):
        with pytest.raises(SourceFailure) as e:
            transport.get('http://issuer.example/a',100)
    assert e.value.code==SourceErrorCode.NETWORK_ERROR


def test_dns_empty_or_bad_resolution():
    for fn in (lambda host,port,type: [], lambda host,port,type: (_ for _ in ()).throw(OSError('no host'))):
        with pytest.raises(SourceFailure) as e:
            public_addresses('issuer.example',443,resolve=fn)
        assert e.value.code==SourceErrorCode.DNS_UNSAFE


def test_snap_store_existing_and_bad_encoding(tmp_path):
    store=SnapshotStore(tmp_path)
    s=snap(); h=store.put(s)
    assert store.put(s)==h
    p=tmp_path/(h+'.json')
    p.write_bytes(b'{}')
    with pytest.raises(SourceFailure):
        store.get(h)
    with pytest.raises(SourceFailure):
        store.put(s)  # corrupted on-disk entry must never be overwritten silently


def test_store_rejects_large_envelope(tmp_path):
    store=SnapshotStore(tmp_path)
    h='e'*64; (tmp_path/(h+'.json')).write_bytes(b' '*13_000_001)
    with pytest.raises(SourceFailure): store.get(h)


def test_incomplete_formal_source_always_blocks_positive_assurance():
    s=snap(b'<main>Corrigendum <table><tr><td>Post</td><td>Deadline</td></tr></table></main>')
    p=parse_snapshot(s)
    assert p.status=='PARTIAL'
    doc=admit_document(s,p,identity(),'d',DocumentRole.CORRIGENDUM,registry())
    from app.domain.enums import ParserStatus,BlockingImpact
    assert doc.parser_status==ParserStatus.PARTIAL
    assert doc.blocking_impact==BlockingImpact.POTENTIAL_GOVERNING


def test_iframe_content_is_partial():
    p=parse_snapshot(snap(b'<main>Notice for internship on time <iframe src="/actual-corrigendum"></iframe></main>'))
    assert p.status=='PARTIAL'
    assert 'HTML_EMBEDDED_CONTENT_UNVERIFIED' in p.warning_codes


def test_fetch_constructor_bounds():
    for kwargs in ({'max_bytes':0},{'max_bytes':-1},{'max_bytes':9_000_000},
                   {'max_redirects':-1},{'max_redirects':4}):
        with pytest.raises(ValueError): SafeSourceFetcher(**kwargs)


@pytest.mark.parametrize('url', [
    'https://issuer.example/a?access_token=secret',
    'https://issuer.example/a?apikey=secret',
    'https://issuer.example/a?X-Amz-Signature=secret',
    'https://issuer.example/a?authorization=secret',
])
def test_sensitive_query_parameters_are_rejected_not_persisted(url):
    with pytest.raises(SourceFailure):
        safe_target(url)

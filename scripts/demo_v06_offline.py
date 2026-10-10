"""Synthetic zero-network demonstration of source-byte → exact-quote → NoticeDocument."""
from __future__ import annotations
import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.sources import (
    SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation,
    parse_snapshot, ground_exact_quote, admit_document,
)
from app.domain.models import NoticeIdentity
from app.domain.enums import CriticalField, DocumentRole, SourceClass, ParserStatus

class SyntheticTransport:
    def get(self, url, max_bytes):
        assert url == 'https://issuer.example/corrigendum'
        return 200, {'content-type':'text/html'}, (
            b'<main><h1>Corrigendum</h1><p>Reference: A/2026</p>'
            b'<p>Deadline extended to 26 October 2026</p></main>')


def main():
    snapshot = SafeSourceFetcher(transport=SyntheticTransport()).fetch(
        'https://issuer.example/corrigendum')
    parsed = parse_snapshot(snapshot)
    quote = '26 October 2026'
    span = ground_exact_quote(snapshot, parsed, quote)
    # This is a SYNTHETIC fixture: the registry entry is NOT proof of a real institution.
    registry = IssuerAuthorityRegistry((AuthorityAttestation(
        issuer_id='synthetic-issuer',exact_host='issuer.example',
        verification_evidence_url='https://directory.example/synthetic-issuer',
        verification_method='MANUAL_CROSS_LINK',verified_at=datetime.now(timezone.utc)),))
    document = admit_document(snapshot,parsed,
        NoticeIdentity(issuer_id='synthetic-issuer',reference_numbers=('A/2026',)),
        'synthetic-corrigendum',DocumentRole.CORRIGENDUM,registry,
        grounded_fields=((CriticalField.DEADLINE,quote,date(2026,10,26),span),))
    assert parsed.status == 'PARSED'
    assert document.source_class == SourceClass.ISSUER_PRIMARY
    assert document.parser_status == ParserStatus.PARSED
    assert document.fields[0].normalized_value == date(2026,10,26)
    print(json.dumps({
        'demo_mode':'SYNTHETIC_OFFLINE',
        'source_sha256':snapshot.body_sha256,
        'text_sha256':parsed.normalized_text_sha256,
        'quotation':span.quotation,
        'document_role':document.document_role.value,
        'deadline':document.fields[0].normalized_value.isoformat(),
        'result':'INGESTION_GATE_PASS',
        'note':'No SerpApi call, live authority claim or governing verdict was produced.'
    },indent=2))

if __name__ == '__main__':
    main()

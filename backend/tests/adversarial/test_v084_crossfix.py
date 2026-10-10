"""v0.8.4 interactions: integrity gates remain safe when fixes compose."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.main import create_app
from app.application.models import NoticeCheckRequest
from app.application.workflow import NoticeWorkflow
from app.domain.enums import Verdict
from app.search.models import PlannedQuery, QueryTier, QueryPurpose, SearchStatus, SearchMode
from app.search.client import parse_provider_payload
from app.sources import AuthorityAttestation, IssuerAuthorityRegistry


def attested(**overrides):
    args = dict(issuer_id='audit', exact_host='issuer.example',
        verification_evidence_url='https://directory.example/proof',
        verified_at=datetime.now(timezone.utc), verification_method='MANUAL_CROSS_LINK',
        canonical_issuer_name='Audit Issuer', publication_path_prefixes=('/notices',))
    args.update(overrides)
    return AuthorityAttestation(**args)


def test_issuer_name_is_operator_metadata_not_request_control():
    r = IssuerAuthorityRegistry((attested(),))
    assert r.issuer_label('audit') == 'Audit Issuer'
    assert r.issuer_label('unknown') is None
    assert r.verified('audit', 'https://issuer.example/notices/main')
    assert not r.verified('audit', 'https://issuer.example/user-content/main')
    assert not r.verified('audit', 'https://issuer.example/blog/main')
    assert not r.verified('audit', 'http://issuer.example/notices/main')


def test_issuer_path_prefix_segment_boundary():
    r = IssuerAuthorityRegistry((attested(),))
    assert r.verified('audit', 'https://issuer.example/notices')
    assert not r.verified('audit', 'https://issuer.example/notices-uploads/file')
    assert not r.verified('audit', 'https://issuer.example/notices/user-uploads/file')
    assert not r.verified('audit', 'https://issuer.example/notices/%75ser-content/file')


def test_expired_and_future_attestation_both_not_current():
    expired = IssuerAuthorityRegistry((attested(verified_at=datetime.now(timezone.utc)-timedelta(days=366)),))
    future = IssuerAuthorityRegistry((attested(verified_at=datetime.now(timezone.utc)+timedelta(days=2)),))
    assert not expired.approved_hosts('audit')
    assert not future.approved_hosts('audit')


def test_preflight_rejects_unsafe_original_url_before_provider():
    kwargs = dict(issuer_id='audit', issuer_name='Audit Issuer', reference_number='A/2026',
        supplied_deadline=date(2026, 10, 1), as_of=datetime(2026, 10, 8, tzinfo=timezone.utc))
    for bad in ('ftp://issuer.example/file','https://user:pass@issuer.example/p',
                'https://127.0.0.1/a','https://issuer.example/'+'x'*5000):
        with pytest.raises(ValidationError):
            NoticeCheckRequest(**kwargs, original_url=bad)


def test_provider_truncation_error_is_serializable_and_no_false_results():
    q = PlannedQuery(query='"A/2026"', purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE,priority=1)
    payload = {'search_metadata':{'status':'Success'}, 'organic_results':[
        {'link':f'https://issuer.example/notices/item/{i}'} for i in range(101)]}
    r = parse_provider_payload(payload,q,captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)
    assert r.status == SearchStatus.ERROR
    assert r.error_code == 'PROVIDER_RESULT_TRUNCATED'
    assert r.results == ()
    assert r.response_sha256 and len(r.response_sha256) == 64


def test_invalid_length_header_is_controlled():
    with TestClient(create_app(None)) as client:
        r=client.post('/api/demo/check',content=b'{}',headers={
            'content-type':'application/json','content-length':'abc'})
    assert r.status_code == 400


def test_exact_api_body_limit_accepts_small_and_rejects_large():
    with TestClient(create_app(None)) as client:
        assert client.post('/api/demo/check',json={'supplied_deadline':'2026-10-01'}).status_code == 200
        r=client.post('/api/demo/check',content=b'{"supplied_deadline":"2026-10-01"}' + b' '*70000,
                 headers={'content-type':'application/json'})
    assert r.status_code == 413


def test_operator_attestation_without_name_never_claims_name_as_verified():
    r = IssuerAuthorityRegistry((attested(canonical_issuer_name=None),))
    assert r.issuer_label('audit') is None
    assert r.verified('audit', 'https://issuer.example/notices/a')


def test_invalid_operator_publication_prefixes_fail_during_configuration():
    for prefixes in (('not-absolute',), ('/notices/../private',), ('/notices%2fprivate',),
                     tuple('/p/'+str(i) for i in range(13))):
        with pytest.raises(ValidationError):
            attested(publication_path_prefixes=prefixes)
    with pytest.raises(ValidationError):
        attested(canonical_issuer_name=' ')


def test_mixed_or_conflicting_issuer_labels_cannot_be_considered_canonical():
    r=IssuerAuthorityRegistry((attested(), attested(exact_host='second.example',
        canonical_issuer_name='Different Institution')))
    assert r.issuer_label('audit') is None


def test_real_mode_must_have_reviewed_publication_policy_before_search():
    without = IssuerAuthorityRegistry((attested(publication_path_prefixes=()),))
    with_policy = IssuerAuthorityRegistry((attested(),))
    assert not without.live_publication_policy_ready('audit')
    assert with_policy.live_publication_policy_ready('audit')
    assert not with_policy.live_publication_policy_ready('absent')

@pytest.mark.asyncio
async def test_live_workflow_fails_before_search_without_reviewed_paths():
    from app.sources import SafeSourceFetcher
    from app.domain.enums import Verdict
    class CannotSearch:
        async def execute(self,*args,**kwargs):
            raise AssertionError('provider should never be called')
    registry = IssuerAuthorityRegistry((attested(publication_path_prefixes=()),))
    workflow=NoticeWorkflow(executor=CannotSearch(),fetcher=SafeSourceFetcher(),
        registry=registry,evidence_mode='NETWORK')
    req = NoticeCheckRequest(issuer_id='audit',issuer_name='Audit Issuer',reference_number='A/2026',
        supplied_deadline=date(2026,10,1), as_of=datetime.now(timezone.utc)-timedelta(minutes=10),
        original_url='https://issuer.example/notices/original')
    out = await workflow.check(req)
    assert out.analysis.verdict == Verdict.UNRESOLVED
    assert out.provider_calls == 0
    assert 'NO_OPERATOR_VERIFIED_PUBLICATION_SCOPE' in out.warnings


def test_invalid_host_or_scheme_never_becomes_operator_attested():
    registry=IssuerAuthorityRegistry((attested(),))
    assert not registry.verified('audit','https://evil.example/notices/p')
    assert not registry.verified('audit','ftp://issuer.example/notices/p')
    assert not registry.verified('absent','https://issuer.example/notices/p')


def test_media_rule_affecting_decisive_html_is_not_silently_ignored():
    from hashlib import sha256
    from app.sources import parse_snapshot
    from app.sources.models import SourceSnapshot
    html=(b'<html><head><style>@media screen and (max-width:600px) {'
          b'.hiddennotice {display:none} }</style></head><body><main>'
          b'<p class="hiddennotice">The deadline is extended from Oct 1 to Oct 26</p>'
          b'<p>Reference A/2026 and published original conditions</p></main></body></html>')
    snapshot=SourceSnapshot(source_url='https://issuer.example/notices/a',
        final_url='https://issuer.example/notices/a',captured_at=datetime.now(timezone.utc),
        content_type='text/html',body=html,body_sha256=__import__('hashlib').sha256(html).hexdigest())
    parsed=parse_snapshot(snapshot)
    assert parsed.status != 'PARSED'
    assert 'CSS_RESPONSIVE_VISIBILITY_UNVERIFIED' in parsed.warning_codes


def test_responsive_visibility_rule_matching_main_root_is_not_admitted():
    from hashlib import sha256
    from app.sources import parse_snapshot
    from app.sources.models import SourceSnapshot
    html=b'''<html><head><style>@media print {.notice {display:none}}</style></head>
        <body><main class="notice"><h2>Application deadline</h2>
        <p>Reference A/2026 issued 2026-09-17</p></main></body></html>'''
    s=SourceSnapshot(source_url='https://issuer.example/notices/a',
      final_url='https://issuer.example/notices/a',content_type='text/html',
      captured_at=datetime.now(timezone.utc),body=html,body_sha256=sha256(html).hexdigest())
    parsed=parse_snapshot(s)
    assert parsed.status != 'PARSED'
    assert 'CSS_RESPONSIVE_VISIBILITY_UNVERIFIED' in parsed.warning_codes


def test_unsupported_responsive_selector_fails_closed():
    from hashlib import sha256
    from app.sources import parse_snapshot
    from app.sources.models import SourceSnapshot
    html=b'''<html><head><style>@media print { main.notice {visibility:hidden}}</style></head>
        <body><main class="notice"><h2>Application deadline</h2>
        <p>Reference A/2026 issued 2026-09-17</p></main></body></html>'''
    s=SourceSnapshot(source_url='https://issuer.example/notices/a',
      final_url='https://issuer.example/notices/a',content_type='text/html',
      captured_at=datetime.now(timezone.utc),body=html,body_sha256=sha256(html).hexdigest())
    parsed=parse_snapshot(s)
    assert parsed.status == 'PARTIAL'
    assert 'CSS_VISIBILITY_UNVERIFIED' in parsed.warning_codes

"""Independent regression specifications; written against unchanged NoticeDrift v0.8.3.
A failing assertion indicates a gap against the named safety/reliability contract.
No outbound network is used.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone
from hashlib import sha256
import pytest
from pydantic import ValidationError
from app.application.models import NoticeCheckRequest
from app.application.workflow import NoticeWorkflow
from app.domain.enums import Verdict
from app.search.executor import SearchExecutor
from app.search.models import SearchMode, SearchStatus, OrganicResult
from app.search.client import parse_provider_payload
from app.sources import SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation, parse_snapshot
from app.sources.models import SourceSnapshot

ORIGINAL='https://issuer.example/notices/a'
CORRECTION='https://issuer.example/notices/corrigendum'
ORIG_HTML=b'<main>Reference: A/2026\nIssued: 2026-09-01\nApplication deadline: 01 October 2026</main>'
UPDATE_HTML=b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\nThe deadline is extended from 01 October 2026 to 26 October 2026.</main>'

def request(**kwargs):
    data=dict(issuer_id='audit', issuer_name='Audit Issuer', reference_number='A/2026',
          supplied_deadline=date(2026,10,1),as_of=datetime(2026,10,8,tzinfo=timezone.utc),
          original_url=ORIGINAL)
    data.update(kwargs)
    return NoticeCheckRequest(**data)

class FakeTransport:
    def __init__(self, bodies): self.bodies=bodies; self.calls=[]
    def get(self,url,max_bytes):
        self.calls.append(url)
        return 200, {'content-type':'text/html'}, self.bodies[url]

class FakeClient:
    def __init__(self, results): self.results=results; self.calls=0
    async def search(self, planned, **params):
        self.calls+=1
        payload={'search_metadata':{'status':'Success'}, 'organic_results':self.results}
        return parse_provider_payload(payload, planned, captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)

def workflow(results,bodies):
    client=FakeClient(results)
    transport=FakeTransport(bodies)
    reg=IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='audit',exact_host='issuer.example',
       verified_at=datetime.now(timezone.utc), verification_evidence_url='https://issuer.example/directory',
       verification_method='MANUAL_CROSS_LINK', canonical_issuer_name='Audit Issuer'),))
    return NoticeWorkflow(executor=SearchExecutor(client,simulation=True),
      fetcher=SafeSourceFetcher(transport=transport),registry=reg,evidence_mode='SYNTHETIC_OFFLINE'),client,transport


def test_no_silent_truncation_of_provider_results():
    from app.search.models import PlannedQuery, QueryPurpose, QueryTier
    planned=PlannedQuery(query='"A/2026"',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    organic=[{'link':f'https://other.example/p/{n}'} for n in range(100)]
    organic.append({'link':CORRECTION,'title':'Corrigendum A/2026'})
    resp=parse_provider_payload({'search_metadata':{'status':'Success'},'organic_results':organic},planned,
      captured=datetime.now(timezone.utc),mode=SearchMode.SYNTHETIC)
    assert resp.status is SearchStatus.ERROR or len(resp.results)==len(organic), '101st governing candidate silently discarded with OK status'


@pytest.mark.asyncio
async def test_positive_verdict_cannot_ignore_overflowed_official_corrigendum():
    organic=[{'link':f'https://other.example/p/{n}','title':'unrelated result'} for n in range(100)]
    organic.append({'link':CORRECTION,'title':'Corrigendum A/2026'})
    engine,client,transport=workflow(organic,{ORIGINAL:ORIG_HTML,CORRECTION:UPDATE_HTML})
    outcome=await engine.check(request())
    assert outcome.analysis.verdict != Verdict.SUPPORTED_BY_EVIDENCE, 'Missed known official correction while returning positive assurance'


@pytest.mark.asyncio
async def test_invalid_original_url_must_not_consume_paid_searches():
    engine,client,transport=workflow([], {ORIGINAL:ORIG_HTML})
    invalid='https://issuer.example/' + 'x'*5000
    try:
        req=request(original_url=invalid)
    except ValidationError:
        return
    outcome=await engine.check(req)
    assert client.calls==0, f'{client.calls} paid search equivalents spent on URL known to violate fetcher URL length limit'


def test_input_schema_denies_overlong_original_url_before_i_o():
    with pytest.raises(ValidationError):
        request(original_url='https://issuer.example/' + 'x'*5000)


def test_unrelated_responsive_css_does_not_invalidate_visible_official_notice():
    html=(b'<html><head><style>@media screen and (max-width:600px) { .menu {display:none} }</style></head>'
          b'<body><main>Reference: A/2026\nIssued: 2026-09-01\nApplication deadline: 01 October 2026</main></body></html>')
    snapshot=SourceSnapshot(source_url=ORIGINAL,final_url=ORIGINAL,
        captured_at=datetime.now(timezone.utc),content_type='text/html',body=html,body_sha256=sha256(html).hexdigest())
    parsed=parse_snapshot(snapshot)
    assert parsed.status=='PARSED', f'Irrelevant CSS caused conservative refusal: {parsed.status}, {parsed.warning_codes}'


@pytest.mark.asyncio
async def test_identity_changes_to_unrelated_user_issuer_name_do_not_create_fake_claim():
    organic=[{'link':ORIGINAL},{'link':CORRECTION}]
    engine,_,_=workflow(organic,{ORIGINAL:ORIG_HTML,CORRECTION:UPDATE_HTML})
    outcome=await engine.check(request(issuer_name='Totally Unrelated Institution'))
    assert outcome.analysis.verdict == Verdict.UNRESOLVED, 'Source only identifies ref and approved host, not claimed issuing institution'

@pytest.mark.asyncio
async def test_unrelated_external_search_noise_does_not_block_proven_official_change():
    organic=[{'link':'https://another.example/blog', 'title':'Audit Issuer corrigendum', 'snippet':'Note A/2026 extension'},
             {'link':ORIGINAL}, {'link':CORRECTION}]
    engine,_,_=workflow(organic,{ORIGINAL:ORIG_HTML,CORRECTION:UPDATE_HTML})
    outcome=await engine.check(request())
    assert outcome.analysis.verdict == Verdict.SUPERSEDED, 'Untrusted web claim forced abstention despite two verified issuer-host documents'


@pytest.mark.asyncio
async def test_official_result_noise_cannot_exhaust_source_cap_before_relevance_screen():
    # A search for a broad government site often returns many unrelated pages.
    pages={ORIGINAL:ORIG_HTML,CORRECTION:UPDATE_HTML}
    for n in range(13):
        pages[f'https://issuer.example/irrelevant/{n}']=(b'<main>Official lunch schedule. Breakfast lunch dinner.</main>')
    organic=[{'link':ORIGINAL,'title':'Original A/2026'}]
    organic += [{'link':f'https://issuer.example/irrelevant/{n}','title':'Unrelated notice'} for n in range(13)]
    organic += [{'link':CORRECTION,'title':'Corrigendum A/2026'}]
    engine,_,_=workflow(organic,pages)
    out=await engine.check(request())
    assert out.analysis.verdict == Verdict.SUPERSEDED, f'{out.analysis.verdict}: {out.warnings}'


def test_old_authority_attestation_should_not_be_unboundedly_trusted():
    from app.sources import IssuerAuthorityRegistry, AuthorityAttestation
    r=IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='audit',exact_host='issuer.example',
       verified_at=datetime(2000,1,1,tzinfo=timezone.utc),verification_evidence_url='https://issuer.example/index',
       verification_method='MANUAL_CROSS_LINK'),))
    assert not r.approved_hosts('audit'), '26-year-old authority attestation remains valid indefinitely without recheck'


@pytest.mark.asyncio
async def test_positive_result_cannot_claim_future_as_of_even_within_clock_skew_allowance():
    from datetime import timedelta
    engine,_,_=workflow([{'link':ORIGINAL}],{ORIGINAL:ORIG_HTML})
    future=datetime.now(timezone.utc)+timedelta(minutes=2)
    outcome=await engine.check(request(as_of=future))
    assert outcome.analysis.verdict == Verdict.UNRESOLVED, 'positive assurance is about a future as_of timestamp'

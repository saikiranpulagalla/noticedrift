"""Zero-credit, synthetic E2E test fixture for the judge-facing experience.

Everything with issuer.example is invented demonstration data. This exercises the
same NoticeWorkflow, search planner/executor, HTML parser, evidence grounding,
authority checks and resolver as normal; the external I/O is mocked only.
"""
from __future__ import annotations
from datetime import datetime, date, timezone

from app.application.models import NoticeCheckRequest, CheckOutcome
from app.application.workflow import NoticeWorkflow
from app.search import SearchExecutor, SearchResponse, SearchStatus, SearchMode, OrganicResult
from app.sources import SafeSourceFetcher, IssuerAuthorityRegistry, AuthorityAttestation

FIXTURE_ORIGINAL = 'https://issuer.example/notice'
FIXTURE_CORRIGENDUM = 'https://issuer.example/corrigendum'
FIXTURE_PAGES = {
    FIXTURE_ORIGINAL: b'<main>Official Notice\nReference: A/2026\nIssued: 2026-09-01\nApplication deadline: 01 October 2026</main>',
    FIXTURE_CORRIGENDUM: b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\nThe deadline is extended from 01 October 2026 to 26 October 2026</main>',
}


class DemoTransport:
    def get(self, url: str, max_bytes: int):
        if url not in FIXTURE_PAGES:
            raise ValueError('DEMO_SOURCE_NOT_FOUND')
        return 200, {'content-type': 'text/html'}, FIXTURE_PAGES[url]


class DemoSearch:
    async def search(self, planned, **params):
        if params.get('no_cache') is not True:
            raise ValueError('DEMO_REQUIRES_FRESH_SEMANTICS')
        return SearchResponse(
            query=planned, mode=SearchMode.SYNTHETIC, status=SearchStatus.OK,
            captured_at=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc),
            provider_cached=False, provider_status='Success',
            results=tuple(OrganicResult(link=url) for url in FIXTURE_PAGES),
        )


async def run_demo(supplied_deadline: date) -> CheckOutcome:
    registry = IssuerAuthorityRegistry((AuthorityAttestation(
        issuer_id='fixture-only', exact_host='issuer.example',
        verification_evidence_url='https://directory.example/fictional',
        verification_method='MANUAL_CROSS_LINK',
        verified_at=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc),
    ),))
    runner = NoticeWorkflow(
        executor=SearchExecutor(DemoSearch(), simulation=True),
        fetcher=SafeSourceFetcher(transport=DemoTransport()),
        registry=registry, evidence_mode='SYNTHETIC_OFFLINE',
    )
    req = NoticeCheckRequest(
        issuer_id='fixture-only', issuer_name='Fixture Issuer',
        reference_number='A/2026', supplied_deadline=supplied_deadline,
        as_of=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc),
    )
    return await runner.check(req)

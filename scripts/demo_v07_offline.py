"""Zero-provider-credits end-to-end demonstration. All domains/data are synthetic."""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime,date,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.application.models import NoticeCheckRequest
from app.application.workflow import NoticeWorkflow
from app.search import SearchExecutor,SearchResponse,SearchStatus,SearchMode,OrganicResult
from app.sources import SafeSourceFetcher,IssuerAuthorityRegistry,AuthorityAttestation

URL1='https://issuer.example/notice'
URL2='https://issuer.example/corrigendum'
PAGES={
 URL1: b'<main>Official Notice\nReference: A/2026\nIssued: 2026-09-01\nApplication deadline: 01 October 2026</main>',
 URL2: b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\nThe deadline is extended from 01 October 2026 to 26 October 2026</main>',
}
class FixtureTransport:
    def get(self,url,max_bytes):
        assert url in PAGES
        return 200, {'content-type':'text/html'}, PAGES[url]
class FixtureSearch:
    async def search(self,planned,**params):
        assert params.get('no_cache') is True
        return SearchResponse(query=planned,mode=SearchMode.LIVE,status=SearchStatus.OK,
            captured_at=datetime.now(timezone.utc),provider_cached=False,
            provider_status='Success',results=tuple(OrganicResult(link=u) for u in PAGES))

async def main():
    registry=IssuerAuthorityRegistry((AuthorityAttestation(
       issuer_id='fixture-only',exact_host='issuer.example',
       verification_evidence_url='https://directory.example/fictional',
       verification_method='MANUAL_CROSS_LINK',verified_at=datetime.now(timezone.utc)),))
    runner=NoticeWorkflow(executor=SearchExecutor(FixtureSearch()),
        fetcher=SafeSourceFetcher(transport=FixtureTransport()),registry=registry,
        evidence_mode='SYNTHETIC_OFFLINE')
    req=NoticeCheckRequest(issuer_id='fixture-only',issuer_name='Fixture Issuer',
        reference_number='A/2026',supplied_deadline=date(2026,10,1),
        as_of=datetime(2026,10,8,tzinfo=timezone.utc))
    out=await runner.check(req)
    print(json.dumps(out.model_dump(mode='json'),indent=2))
    if out.analysis.verdict.value!='SUPERSEDED' or len(out.sources)!=2:
        raise SystemExit('FAIL: V0.7_SYNTHETIC_E2E')
    print('PASS: V0.7_SYNTHETIC_E2E (NO REAL SERPAPI OR ISSUER AUTHORITY CLAIM)')
if __name__=='__main__':
    asyncio.run(main())

"""Independent v0.8.4 audit probes; added outside the uploaded archive.
No network, secrets, or provider credits are used.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta, date
from hashlib import sha256
from pathlib import Path
import os
import tempfile
import threading
import time
from urllib.parse import unquote
import pytest

from app.sources.evidence import IssuerAuthorityRegistry
from app.sources.models import AuthorityAttestation, SourceSnapshot
from app.sources.store import SnapshotStore
from app.sources.parse import parse_snapshot
from app.application.workflow import NoticeWorkflow
from app.application.models import NoticeCheckRequest
from app.domain.enums import Verdict
from app.search.models import SearchResponse, SearchStatus, SearchMode, OrganicResult
from app.search.executor import SearchExecutor
from app.sources.fetch import SafeSourceFetcher

ORIGINAL='https://issuer.example/notices/original'
UPDATE='https://issuer.example/notices/update'
ORIG_HTML=b'<main>Reference: A/2026\nIssued: 2026-09-01\nApplication deadline: 01 October 2026</main>'
UPDATE_HTML=b'<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\nThe deadline is extended from 01 October 2026 to 26 October 2026</main>'

def registry():
    return IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='audit',exact_host='issuer.example',
        canonical_issuer_name='Audit Issuer',publication_path_prefixes=('/notices',),
        verification_evidence_url='https://directory.example/manual',
        verified_at=datetime.now(timezone.utc),verification_method='MANUAL_CROSS_LINK'),))

def snap(body=ORIG_HTML,url=ORIGINAL,when=None):
    return SourceSnapshot(source_url=url,final_url=url,captured_at=when or datetime.now(timezone.utc),
        content_type='text/html',body=body,body_sha256=sha256(body).hexdigest())

class Search:
    def __init__(self, urls):self.urls=urls;self.calls=0
    async def search(self, planned, **kwargs):
        self.calls+=1
        return SearchResponse(query=planned,mode=SearchMode.SYNTHETIC,status=SearchStatus.OK,
            captured_at=datetime.now(timezone.utc),provider_cached=False,provider_status='Success',
            results=tuple(OrganicResult(link=u) for u in self.urls))
class Transport:
    def __init__(self, pages):self.pages=pages
    def get(self,url,max_bytes):return 200,{'content-type':'text/html'},self.pages[url]

def workflow(pages=None,*,store=None):
    pages=pages or {ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML}
    search=Search(list(pages))
    wf=NoticeWorkflow(executor=SearchExecutor(search,simulation=True),
        fetcher=SafeSourceFetcher(transport=Transport(pages)),registry=registry(),
        evidence_mode='SYNTHETIC_OFFLINE',snapshot_store=store)
    return wf,search

def req():
    return NoticeCheckRequest(issuer_id='audit',issuer_name='Audit Issuer',reference_number='A/2026',
        supplied_deadline=date(2026,10,1),as_of=datetime(2026,10,8,tzinfo=timezone.utc),
        original_url=ORIGINAL)

@pytest.mark.parametrize('path',[
    '/notices/%2e%2e/other',
    '/notices/%2e%2e%2fother',
    '/notices/%2575%2573er-uploads/letter',
    '/notices/%252e%252e%252fother',
])
def test_publication_policy_must_refuse_path_canonicalization_ambiguities(path):
    u='https://issuer.example'+path
    allowed=registry().verified('audit',u)
    print('ENCODED_PATH',path,'decoded_once',unquote(path),'allowed',allowed)
    assert allowed is False


def test_snapshot_write_must_not_depend_on_unix_only_fchmod(monkeypatch,tmp_path):
    # Recreates running this exact code where os.fchmod is unavailable, as on
    # Windows builds. Only optional permission enforcement should differ.
    monkeypatch.delattr(os, 'fchmod', raising=False)
    store=SnapshotStore(tmp_path)
    result=store.put(snap())
    assert store.get(result).body == ORIG_HTML

@pytest.mark.asyncio
async def test_full_workflow_survives_missing_fchmod_or_abstains_instead_of_crashing(monkeypatch,tmp_path):
    monkeypatch.delattr(os,'fchmod',raising=False)
    runner,search=workflow(store=SnapshotStore(tmp_path))
    try:
        result=await runner.check(req())
    except Exception as e:
        pytest.fail('Unhandled storage portability failure: '+type(e).__name__)
    assert result.analysis.verdict in (Verdict.SUPERSEDED,Verdict.UNRESOLVED)


def test_identical_source_bytes_dont_consume_unbounded_evidence_files(tmp_path):
    store=SnapshotStore(tmp_path)
    ids=[]
    for i in range(25):
        ids.append(store.put(snap(when=datetime(2026,10,8,tzinfo=timezone.utc)+timedelta(seconds=i))))
    count=len(list(tmp_path.glob('*.json')))
    print('SNAPSHOT_DUPLICATION',len(set(ids)),'unique_ids',count,'files','identical_raw_sha',snap().body_sha256)
    assert count == 25, 'Distinct capture times must remain independently replayable'
    constrained = SnapshotStore(tmp_path / 'quota', max_snapshots=2)
    constrained.put(snap(when=datetime(2026,10,8,tzinfo=timezone.utc)))
    constrained.put(snap(when=datetime(2026,10,8,0,0,1,tzinfo=timezone.utc)))
    with pytest.raises(Exception, match='OVERSIZED'):
        constrained.put(snap(when=datetime(2026,10,8,0,0,2,tzinfo=timezone.utc)))

@pytest.mark.asyncio
async def test_cancelled_request_does_not_release_late_running_parse_worker(monkeypatch):
    from app.application import workflow as wfmod
    real=wfmod.parse_snapshot
    started=threading.Event();finished=threading.Event()
    def slow(*args,**kwargs):
        started.set();time.sleep(.22)
        try:return real(*args,**kwargs)
        finally:finished.set()
    monkeypatch.setattr(wfmod,'parse_snapshot',slow)
    runner,_=workflow()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(runner.check(req()),timeout=.07)
    assert started.is_set()
    print('CANCELLED_PARSE_WORKER_FINISHED',finished.is_set())
    assert finished.is_set(), 'Untracked parse worker continues after check task is cancelled'


@pytest.mark.asyncio
async def test_encoded_user_upload_corrective_document_cannot_govern(tmp_path):
    encoded='https://issuer.example/notices/%2575%2573er-uploads/corrigendum'
    runner,_=workflow({ORIGINAL:ORIG_HTML,encoded:UPDATE_HTML},store=SnapshotStore(tmp_path))
    out=await runner.check(req())
    print('ENCODED_UPLOAD_FINAL_VERDICT',out.analysis.verdict, 'warnings',out.warnings)
    assert out.analysis.verdict == Verdict.UNRESOLVED

@pytest.mark.asyncio
async def test_cancelled_request_keeps_snapshot_store_worker_accounted(monkeypatch,tmp_path):
    original=SnapshotStore.put
    started=threading.Event();finished=threading.Event()
    def slow_store(self,snapshot):
        started.set();time.sleep(.22)
        try:return original(self,snapshot)
        finally:finished.set()
    monkeypatch.setattr(SnapshotStore,'put',slow_store)
    runner,_=workflow(store=SnapshotStore(tmp_path))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(runner.check(req()),timeout=.065)
    assert started.is_set()
    print('CANCELLED_STORE_WORKER_FINISHED',finished.is_set())
    assert finished.is_set()

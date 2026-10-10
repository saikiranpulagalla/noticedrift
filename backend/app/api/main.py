"""FastAPI v0.7 adapter. No issuer authority is accepted from user requests.

Only configured, manually corroborated exact issuer hosts can govern.
"""
from __future__ import annotations
import json
import os
import asyncio
import time
from hashlib import sha256
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from datetime import date
from app.api.site import SITE
from app.application.demo import run_demo
from app.application.reference_case import official_reference_case
from app.application.live_diagnostic import latest_live_search_diagnostic
from app.application.models import NoticeCheckRequest, CheckOutcome
from app.application.workflow import NoticeWorkflow
from app.search import SerpApiClient, SearchExecutor
from app.search.budget import SharedCreditLedger
from app.sources import IssuerAuthorityRegistry, AuthorityAttestation, SafeSourceFetcher, SnapshotStore
from app.version import VERSION


def configured_workflow() -> NoticeWorkflow | None:
    key = os.environ.get('SERPAPI_API_KEY', '')
    manifest_path = os.environ.get('NOTICEDRIFT_ISSUER_ATTESTATIONS', '')
    if not key or not manifest_path:
        return None
    p = Path(manifest_path)
    # Configuration is operator-owned; paths do not come from request payloads.
    if not p.is_file() or p.stat().st_size > 32768:
        return None
    try:
        entries = json.loads(p.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeError, OSError):
        return None
    if not isinstance(entries, list) or not entries or len(entries) > 32:
        return None
    try:
        registry = IssuerAuthorityRegistry(tuple(AuthorityAttestation.model_validate(x) for x in entries))
    except (ValidationError, ValueError, TypeError):
        return None
    # The issuer must attest both canonical authorship and the actual paths
    # from which issuer-authored notices can be published before enabling live.
    if any(not registry.live_publication_policy_ready(entry.issuer_id) for entry in registry._records.values()):
        return None
    evidence_dir = Path(os.environ.get('NOTICEDRIFT_EVIDENCE_DIR', '.noticedrift-evidence'))
    try:
        monthly_limit = int(os.environ.get('NOTICEDRIFT_MONTHLY_SEARCH_LIMIT', '200'))
        ledger = SharedCreditLedger(evidence_dir / 'search-quota.sqlite3', monthly_limit=monthly_limit)
    except (ValueError, OSError, __import__('sqlite3').Error):
        return None
    return NoticeWorkflow(executor=SearchExecutor(SerpApiClient(key), ledger=ledger),
                          fetcher=SafeSourceFetcher(), registry=registry,
                          evidence_mode='NETWORK',
                          snapshot_store=SnapshotStore(evidence_dir))


class DemoCheckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    supplied_deadline: date

def create_app(workflow: NoticeWorkflow | None = None) -> FastAPI:
    app = FastAPI(title='NoticeDrift', version=VERSION)

    @app.middleware('http')
    async def bound_api_request_body(request: Request, call_next):
        # Bound actual streamed bytes; Content-Length alone is attacker-controlled
        # and can be absent or incorrect. This limit is for JSON API requests,
        # not bounded remote HTML/PDF fetches.
        if request.url.path.startswith('/api/') and request.method in {'POST', 'PUT', 'PATCH'}:
            MAX_BODY = 65_536
            header_length = request.headers.get('content-length')
            if header_length:
                try:
                    if int(header_length) > MAX_BODY:
                        return JSONResponse({'detail':'REQUEST_BODY_TOO_LARGE'},status_code=413)
                except ValueError:
                    return JSONResponse({'detail':'INVALID_CONTENT_LENGTH'},status_code=400)
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY:
                    return JSONResponse({'detail':'REQUEST_BODY_TOO_LARGE'},status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        return await call_next(request)
    # Never cache mutable global permission flags from a user's request.
    state = {'workflow':workflow, 'lock':asyncio.Lock(), 'recent':{},
             'inflight': {}, 'distinct_times':[], 'active':0,
             'demo_lock':asyncio.Lock(), 'demo_times':[]}
    # Single-flight per app process for identical checks, plus a conservative
    # admission limit on *distinct* expensive checks. This is NOT an account-wide
    # quota across multiple workers; production requires one worker / gateway.
    max_distinct_per_hour = 12
    max_simultaneous_live = 4
    max_demo_per_minute = 12

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    def home():
        return HTMLResponse(SITE, headers={'Cache-Control':'no-store',
           'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'",
           'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer'})

    @app.get('/api/reference-case')
    def reference_case():
        return official_reference_case()

    @app.get('/api/live-search-diagnostic')
    def live_search_diagnostic():
        # A static, redacted summary only.  It never reads a local ledger,
        # credential, report, or evidence store and it cannot trigger a search.
        return latest_live_search_diagnostic()

    @app.post('/api/demo/check', response_model=CheckOutcome)
    async def demo_check(req: DemoCheckRequest):
        async with state['demo_lock']:
            now = time.monotonic()
            state['demo_times'] = [t for t in state['demo_times'] if now-t < 60]
            if len(state['demo_times']) >= max_demo_per_minute:
                raise HTTPException(status_code=429, detail='DEMO_WORK_LIMIT')
            state['demo_times'].append(now)
        return await run_demo(req.supplied_deadline)

    @app.get('/health')
    def health():
        return {'status':'ok','version':'v'+VERSION,'configured':state['workflow'] is not None}

    @app.get('/api/capabilities')
    def capabilities():
        return {'text_or_url_parsing':'structured-reference-and-deadline-only',
                'supported_relations':['explicit_english_deadline_extension','full_cancellation'],
                'source_formats':['static_html','text_pdf','plain_text'],
                'live_enabled':state['workflow'] is not None,
                'authority':'operator-attested-exact-issuer-host',
                'positive_verdict_limit':'only supported by retrieved evidence, not exhaustively verified'}

    @app.post('/api/check',response_model=CheckOutcome)
    async def check(req: NoticeCheckRequest):
        engine=state['workflow']
        if engine is None:
            raise HTTPException(status_code=503, detail='LIVE_SEARCH_NOT_CONFIGURED')
        body = req.model_dump_json()
        digest = sha256(body.encode('utf-8')).hexdigest()
        async with state['lock']:
            now = time.monotonic()
            state['distinct_times'] = [t for t in state['distinct_times'] if now-t < 3600]
            state['recent'] = {k:v for k,v in state['recent'].items() if now-v[0] < 2.0}
            hit = state['recent'].get(digest)
            if hit is not None:
                previous = hit[1]
                return previous.model_copy(update={'execution_mode':previous.execution_mode+'_RECENT_SHARED', 'origin_provider_calls':previous.origin_provider_calls if previous.origin_provider_calls is not None else previous.provider_calls, 'provider_calls':0})
            task = state['inflight'].get(digest)
            reused = task is not None
            if task is None:
                if len(state['distinct_times']) >= max_distinct_per_hour or state['active'] >= max_simultaneous_live:
                    raise HTTPException(status_code=429,detail='EXPENSIVE_CHECK_RATE_LIMIT')
                state['distinct_times'].append(now)
                state['active'] += 1
                task = asyncio.create_task(engine.check(req, fresh=True))
                state['inflight'][digest] = task

                def completed(future, key=digest):
                    # Release admission even if the requesting client disconnects.
                    async def release():
                        async with state['lock']:
                            if state['inflight'].get(key) is future:
                                state['inflight'].pop(key, None)
                            state['active'] -= 1
                            if not future.cancelled() and future.exception() is None:
                                state['recent'][key] = (time.monotonic(),future.result())
                    asyncio.create_task(release())
                task.add_done_callback(completed)
        # No lock is held across external I/O. Shielding shares the actual
        # provider task among identical callers without cancelling it when a
        # single browser disconnects.
        answer = await asyncio.shield(task)
        return answer.model_copy(update={'execution_mode':answer.execution_mode+'_INFLIGHT_SHARED', 'origin_provider_calls':answer.provider_calls, 'provider_calls':0}) if reused else answer

    return app

app = create_app(configured_workflow())
